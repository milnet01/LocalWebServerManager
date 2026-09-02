"""Spawning and reaping the servers this manager starts.

Core module — no Qt at all, not even QtCore (`docs/standards/coding.md § O1`),
like `ports.py`. Stop needs a worker thread and a plain `ThreadPoolExecutor` is
enough for one; making this a `QObject` would put a Qt dependency into the one
module that spawns processes for a living.

Contract: [`ADR-0003`](../../docs/decisions/0003-launch-via-project-scripts.md),
`docs/design.md § Observability` for the log files, and ADR-0006 for
`LWSM_MANAGED`. The ROADMAP lands three security items here alongside
LWSM-1009 — LWSM-1046 (a discovered launcher is untrusted until confirmed),
LWSM-1047 (signal process handles, never bare PIDs) and LWSM-1048 (the child
environment is an allowlist).

**What this module does NOT do.** It does not show the confirmation dialog
(LWSM-1010 owns the UI), does not drive systemd units (LWSM-1028), does not
tail the log into a `LogBuffer` (LWSM-1011), and does not persist a
confirmation across restarts — `TrustStore` is in-memory until LWSM-1007's
writer exists to hold it. Each of those is a named item, not an oversight.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from lwsm.applog import (
    _prepare_state_dir,
    _require_private_regular_file,
    default_state_dir,
    get_logger,
)
from lwsm.ports import ProbeError, SupportsSnapshot
from lwsm.settings import DEFAULT_LOG_MAX_MIB

log = get_logger(__name__)

# ADR-0003 § Decision, verbatim. An allowlist is a list somebody maintains, so
# the names live here where a reviewer can read them rather than being derived
# from a "looks harmless" predicate — the predicate is what lets the next
# credential-carrying variable through.
ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "TERM",
        "TZ",
        "XDG_RUNTIME_DIR",
        "XDG_SESSION_TYPE",
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
    }
)

# `LC_*` is a family, not a name: `LC_ALL`, `LC_TIME`, `LC_NUMERIC` and six more
# all change how a server formats output. A prefix rather than nine entries.
ENV_ALLOW_PREFIXES = ("LC_",)

# ADR-0003 § Decision: five seconds between SIGTERM and SIGKILL.
GRACE_SECONDS = 5.0

# How long to wait for a process to die once it has been SIGKILLed. Uncatchable,
# so this is a bound on the kernel finishing the job, not on the process
# co-operating.
KILL_TIMEOUT_SECONDS = 2.0

# The wait loops poll rather than block, so a stop can be observed and bounded.
POLL_INTERVAL_SECONDS = 0.02

# `docs/design.md § Observability`: 5 MB with one rotation.
# The DEFAULT cap, aliased from `settings.py` so the settings file's default
# and this one cannot drift (LWSM-1018). The cap actually enforced is
# `Supervisor.max_log_bytes`, which starts here and follows the user's choice.
MAX_LOG_BYTES = DEFAULT_LOG_MAX_MIB * 1024 * 1024
ROTATION_SUFFIX = ".1"


def _open_private_regular(path: Path, flags: int) -> int:
    """Open `path` as a regular file of ours alone, following nothing.

    One function because there were two copies and they had diverged
    (`coding.md § 1.3`): the log's open was hardened and the rotation backup's
    was not, which is exactly the shape a second copy fails in.

    `O_NONBLOCK` belongs in the open rather than beside it. `O_NOFOLLOW`
    refuses a symlink and says nothing about a FIFO, and opening one for
    writing blocks until a reader appears -- forever, on whichever thread
    asked, with no error and no log line. `applog.py` and `configfile.py` were
    both written after measuring that. It is dropped again once the check
    passes, because a regular file must write blocking or a line can be
    short-written.
    """
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        _require_private_regular_file(fd, str(path))
        os.set_blocking(fd, True)
    except BaseException:
        os.close(fd)
        raise
    return fd


_COPY_CHUNK_BYTES = 1 << 20

# A launcher is somebody else's file, so reading it to fingerprint it is a
# bounded read like every other. Larger than `scanner.py`'s cap because this is
# a whole-file hash rather than a line scan, and a 1 MiB shell script is already
# absurd.
MAX_LAUNCHER_BYTES = 1 << 20

# A project name reaches a filename here, and it is hand-edited or scanned text.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
MAX_LOG_NAME_CHARS = 64


class SupervisorError(Exception):
    """Anything this module refuses or fails to do."""


class LauncherRefused(SupervisorError):
    """The launcher is one ADR-0003 § Trust refuses outright.

    Distinct from `LauncherUntrusted`: this one cannot be confirmed away. A
    world-writable launcher is not a thing the user can vouch for, because
    whoever else can write it changes what they vouched for afterwards.
    """


class LauncherUntrusted(SupervisorError):
    """The launcher has not been confirmed, or has changed since it was.

    Carries the material the confirmation must show — ADR-0003: "not security
    theatre only if it shows what will actually run: the resolved path and
    argv, never a friendly summary".
    """

    def __init__(self, resolved: Path | None, argv: tuple[str, ...], fingerprint: str):
        super().__init__(
            f"{resolved or argv[0]} has not been confirmed for this project"
        )
        self.resolved = resolved
        self.argv = argv
        self.fingerprint = fingerprint


class PortAlreadyBound(SupervisorError):
    """The pre-flight check found something already listening on the port.

    Step 1 of every start (`docs/design.md`), and of every restart, since
    ADR-0003 defines restart as "stop then start *with the same pre-flight
    check*". The conflict-warning UI is P07; this is the refusal underneath it.
    """

    def __init__(self, port: int):
        super().__init__(f"port {port} is already bound")
        self.port = port


class AlreadyRunning(SupervisorError):
    """This supervisor already has a child for that project.

    Not a case ADR-0003 discusses, because the UI disables Start while a
    project is running. Refused here anyway: the alternative is that a
    double-click orphans the first child, whose PID we would then have
    forgotten while it still holds the port.
    """


@dataclass(frozen=True)
class StopOutcome:
    """What one stop sequence did, in the order it did it."""

    terminated: tuple[int, ...] = ()
    killed: tuple[int, ...] = ()
    exit_code: int | None = None
    port_still_bound: bool = False
    warning: str | None = None


@dataclass
class ManagedProcess:
    """One child this supervisor spawned, and the handles that identify it."""

    project: Path
    name: str
    popen: subprocess.Popen[bytes]
    handle: psutil.Process
    log_path: Path
    log_fd: int
    port: int | None

    @property
    def pid(self) -> int:
        """Also the process-group id: `start_new_session=True` guarantees it."""
        return self.popen.pid


class TrustStore:
    """Which launchers the user has confirmed, keyed by resolved project path.

    In memory only. ADR-0003's gate is "one-time per-project", which properly
    means one time ever, and that needs the registry writer LWSM-1007 builds —
    so today the confirmation lasts for the session and re-asks on the next
    launch. That is the safe direction to be wrong in, and it is stated rather
    than left for a reader to discover.
    """

    def __init__(self) -> None:
        self._confirmed: dict[Path, str] = {}
        self._lock = threading.Lock()

    def confirm(self, project: Path, fingerprint: str) -> None:
        with self._lock:
            self._confirmed[Path(project).resolve()] = fingerprint

    def is_confirmed(self, project: Path, fingerprint: str) -> bool:
        with self._lock:
            return self._confirmed.get(Path(project).resolve()) == fingerprint

    def revoke(self, project: Path) -> None:
        with self._lock:
            self._confirmed.pop(Path(project).resolve(), None)


# --------------------------------------------------------------------------
# The child environment (LWSM-1048)
# --------------------------------------------------------------------------


def build_child_env(
    port: int | None, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The environment a launched project gets: the allowlist and nothing else.

    `os.environ` passed through would hand every scanned project — including a
    hostile one — `SSH_AUTH_SOCK`, API keys and cloud credentials, readable
    afterwards from `/proc/<pid>/environ` by any other local process.

    `PORT` is set only when there is one. Exporting an empty `PORT` is not the
    same as not exporting it: a launcher reading `${PORT:-3000}` would get the
    empty string instead of its own default, which is precisely the silent
    misconfiguration ADR-0002 case 3 exists to prevent.
    """
    source = os.environ if base is None else base
    env = {
        key: value
        for key, value in source.items()
        if key in ENV_ALLOWLIST or key.startswith(ENV_ALLOW_PREFIXES)
    }
    if port is not None:
        env["PORT"] = str(port)
    # ADR-0006: a presentation hint with no security value. It is unauthenticated
    # and trivially forged, so nothing may be granted or skipped on the strength
    # of it — this is the only place this project sets it.
    env["LWSM_MANAGED"] = "1"
    return env


# --------------------------------------------------------------------------
# The trust gate (LWSM-1046)
# --------------------------------------------------------------------------


def _is_npm_run(argv: tuple[str, ...]) -> bool:
    """`npm run <script>` — the one supported shape that names no file.

    Stated once because two callers need it and they must agree: `_npm_script`
    hashes the manifest string this shape executes, and `start()` refuses any
    other shape that names no launcher (LWSM-1228). A second copy that drifted
    would either hash nothing or refuse a launcher that works.
    """
    return len(argv) == 3 and argv[0] == "npm" and argv[1] == "run"


def _launcher_path(project: Path, argv: tuple[str, ...]) -> Path | None:
    """The file whose contents `argv` executes, if any — refused by the caller.

    Classification only. Whether that file is *acceptable* — inside the
    project, a regular file, not group-writable — is `validate_launcher`'s,
    and `start()` calls it on whatever this returns.

    Two of the four shapes `scanner.py` emits have one. `["./start.sh"]` names
    it directly. `["python3", "serve.py"]` and `["node", "serve.mjs"]` name it
    as the sole argument to a PATH-resolved interpreter — `execve` runs
    `/usr/bin/python3`, but the untrusted content is the script, and that is
    what a confirmation has to be bound to and what `validate_launcher`'s
    refusals have to cover.

    `["npm", "run", "dev"]` has none: what it executes is the `scripts.dev`
    *string* inside `package.json`, which is not a file. `launcher_fingerprint`
    covers that case separately.

    **An `argv[0]` containing no `/` is resolved against `PATH` by `execvp` and
    never against the working directory — POSIX decides this, not path
    arithmetic.** Building `<project>/npm` and letting the caller's `os.stat`
    fail on it refused three of the four launcher kinds outright, with a
    message blaming the user's project for a supervisor bug (LWSM-1132).
    """
    if not argv:
        return None
    if "/" in argv[0]:
        return _contained(project, argv[0])
    # npm's arguments are subcommands, never files — `_npm_script` below is
    # what covers its content. Named explicitly because a *two*-element
    # `npm run` otherwise matches the interpreter shape below on length alone,
    # and a project holding a file called `run` would then have the trust gate
    # vouching for a file that has nothing to do with what executes.
    if argv[0] == "npm":
        return None
    # The interpreter form: one PATH-resolved command, one file it opens.
    if len(argv) == 2:
        return _contained(project, argv[1])
    return None


def _contained(project: Path, name: str) -> Path | None:
    """`name` resolved, or `None` when it names nothing or is the project root.

    **Escaping is deliberately NOT filtered here** — that is the whole of
    LWSM-1162. A symlink leaving the project is a launcher to REFUSE, not a
    launcher we do not have, and returning `None` for it made `_launcher_path`
    give the same answer it gives `npm run dev`. So `validate_launcher` was
    never reached from `start()`, its "outside the project directory" refusal
    was unreachable, and the fingerprint fell through to the `\0nofile\0`
    marker — hashing argv alone, so rewriting the target could not re-arm the
    gate. Containment is `validate_launcher`'s decision, on the resolved target
    that `execve` will actually run; this function only says which file `argv`
    names.
    """
    try:
        resolved = (project / Path(name)).resolve()
        project_resolved = Path(project).resolve()
    except OSError:
        return None
    if resolved == project_resolved:
        return None
    return resolved


def validate_launcher(project: Path, launcher: Path) -> Path:
    """Refuse the launchers ADR-0003 § Trust refuses outright; return the target.

    Two refusals, and they are about the resolved *target* because that is what
    `execve` runs: a symlink leaving the project, and a file any other local
    account can rewrite. A symlink that stays inside the project is fine — the
    ordinary `start.sh -> scripts/start.sh` arrangement — since refusing it
    would fire on the legitimate case, and a rule that does that gets disabled.
    """
    project_resolved = Path(project).resolve()
    try:
        resolved = Path(launcher).resolve()
    except OSError as exc:
        raise LauncherRefused(f"cannot resolve {launcher}: {exc}") from exc

    if not resolved.is_relative_to(project_resolved):
        raise LauncherRefused(
            f"{launcher} resolves to {resolved}, outside the project directory"
        )
    try:
        info = os.stat(resolved)
    except OSError as exc:
        raise LauncherRefused(f"cannot read {resolved}: {exc}") from exc

    if not stat.S_ISREG(info.st_mode):
        raise LauncherRefused(f"{resolved} is not a regular file")
    # Size, because the fingerprint is a bounded read. Hashing the first
    # `MAX_LAUNCHER_BYTES` of a larger file leaves everything past the cap out
    # of the digest, so a change there never re-arms the gate ADR-0003 re-arms
    # on a content change. Refusing here rather than hashing a prefix is
    # `scanner.py`'s discipline, and `start()` reaches this before it
    # fingerprints anything (LWSM-1227).
    if info.st_size > MAX_LAUNCHER_BYTES:
        raise LauncherRefused(
            f"{resolved} is larger than {MAX_LAUNCHER_BYTES} bytes, so it "
            "cannot be fingerprinted whole and a change past the cap would "
            "not re-arm the trust gate"
        )
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise LauncherRefused(
            f"{resolved} is group- or other-writable, so confirming it would "
            "vouch for whatever it is rewritten to say"
        )
    # Ownership, which nothing checked. A file we do not own can be rewritten
    # by whoever does, whatever its mode says. Root is allowed: a root-owned
    # launcher in a directory we control is the ordinary shape of a
    # system-installed one (LWSM-1226).
    if info.st_uid not in (os.getuid(), 0):
        raise LauncherRefused(
            f"{resolved} is owned by uid {info.st_uid}, who can rewrite it "
            "after it is confirmed"
        )
    # And the PARENT, because replacing a file needs write permission on its
    # directory rather than on the file. The refusal above reads the launcher's
    # own mode, and unlink-and-create defeats it outright — `0755` on the file
    # is no protection in a directory anyone else can write.
    #
    # The sticky bit is the exception and it is the common case: `/tmp` is
    # `1777`, and with it set only the owner may unlink, so the replacement
    # this guards against cannot happen.
    try:
        parent = os.stat(resolved.parent)
    except OSError as exc:
        raise LauncherRefused(f"cannot read {resolved.parent}: {exc}") from exc
    writable = parent.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if writable and not parent.st_mode & stat.S_ISVTX:
        raise LauncherRefused(
            f"{resolved.parent} is group- or other-writable without the sticky "
            "bit, so the launcher can be replaced after it is confirmed"
        )
    return resolved


def launcher_fingerprint(project: Path, argv: tuple[str, ...]) -> str:
    """What a confirmation is bound to: the exact argv, plus the launcher's bytes.

    Both halves are load-bearing. Content alone would let a confirmed
    `npm run dev` authorise `npm run deploy`, which reads the same file. Argv
    alone would let `./start.sh` be rewritten after confirmation, which is the
    re-arm ADR-0003 asks for and ADR-0005's merge already detects as *Changed*.
    """
    digest = hashlib.sha256()
    for argument in argv:
        digest.update(argument.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")

    # An explicit marker per material kind rather than just skipping: without
    # one, a launcher that was deleted between two calls fingerprints
    # identically to `npm run dev`, which has no file at all — two different
    # situations reading as one. A third kind needs a third marker for the same
    # reason, so a script's bytes cannot collide with a manifest string.
    candidate = _launcher_path(project, argv)
    content = _launcher_bytes(candidate) if candidate is not None else None
    if content is not None:
        digest.update(b"\0content\0")
        digest.update(content)
        return digest.hexdigest()

    script = _npm_script(project, argv)
    if script is not None:
        digest.update(b"\0npm-script\0")
        digest.update(script)
        return digest.hexdigest()

    digest.update(b"\0nofile\0")
    return digest.hexdigest()


def _npm_script(project: Path, argv: tuple[str, ...]) -> bytes | None:
    """The `scripts.<name>` string an `npm run <name>` argv hands to `/bin/sh`.

    `npm` is on the PATH and runs no file of ours, so `_launcher_path` returns
    `None` for it — but the string it executes is untrusted content living in
    the project, and ADR-0003 § Trust re-arms the gate *"whenever the launcher
    command or its content hash changes"*. A compromised transitive
    dependency's `postinstall` can rewrite `scripts.dev`, which changes what
    runs; without this the confirmation carried straight over to whatever it
    was rewritten to say (LWSM-1140).

    Only the one chosen script, never the whole manifest: re-arming on every
    dependency bump would fire the confirmation dialog during ordinary
    development, and `validate_launcher` already records what happens to a rule
    that does that.

    Every failure here returns `None`, which fingerprints as `\\0nofile\\0` and
    therefore *differs* from a confirmed one — an unreadable or unparseable
    manifest re-arms the gate rather than passing it.
    """
    if not _is_npm_run(argv):
        return None
    raw = _launcher_bytes(project / "package.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    value = scripts.get(argv[2]) if isinstance(scripts, dict) else None
    if not isinstance(value, str):
        return None
    return value.encode("utf-8", "surrogateescape")


def _launcher_bytes(path: Path) -> bytes | None:
    """The launcher's content, or `None` when it is unreadable or over the cap.

    `O_NOFOLLOW` and `O_NONBLOCK` for `scanner.py::_open_source`'s reasons: this
    is somebody else's file, a symlink here would be read straight through, and
    a FIFO planted at `start.sh` would block the fingerprint forever.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, MAX_LAUNCHER_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    # One byte past the cap, so "at the cap" and "over it" are distinguishable.
    # Over it is a refusal, never a prefix: a truncated read hashed as though it
    # were the whole file is the defect `validate_launcher` also refuses
    # (LWSM-1227). An oversize file therefore reaches `launcher_fingerprint`'s
    # `nofile` marker, which it shares with a launcher that does not exist — no
    # loss, because nothing can start one, and a marker of its own would still
    # collide oversize with oversize.
    return None if len(data) > MAX_LAUNCHER_BYTES else data


# --------------------------------------------------------------------------
# Liveness, without reaping anything
# --------------------------------------------------------------------------


def _alive(proc: psutil.Process) -> bool:
    """Running and not a zombie.

    The zombie clause is the point. Our own child stays a zombie between exiting
    and being reaped, and during that window its PID is still reserved — which
    is exactly what makes it safe to keep using as a process-group id. Treating
    a zombie as alive would make the stop sequence wait out its whole grace
    period on a process that is already gone.
    """
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False
    except OSError:
        # `Process.status()` reads /proc; hidepid, an LSM or a vanished entry
        # raise plain OSError, which psutil.Error does not cover (the shape
        # `ports.py` documents for `net_connections`).
        return False


# --------------------------------------------------------------------------
# The supervisor
# --------------------------------------------------------------------------


@dataclass
class _Registry:
    processes: dict[Path, ManagedProcess] = field(default_factory=dict)
    # Projects whose start has been reserved but whose entry is not in
    # `processes` yet. `start()` releases the lock for the port pre-flight, the
    # trust gate, the log open and the spawn, so `processes` alone cannot answer
    # "is one already on its way?" (LWSM-1137).
    starting: set[Path] = field(default_factory=set)
    # The mirror of `starting`, for the other end (LWSM-1168). `stop()` pops the
    # entry out of `processes` under the lock and then runs the whole grace,
    # kill and reap window with the lock released, so `processes` alone cannot
    # answer "is one already on its way OUT?" either.
    stopping: set[Path] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


class Supervisor:
    """Starts, stops and owns the lifetime of every server this manager spawns."""

    def __init__(
        self,
        probe: SupportsSnapshot,
        log_dir: Path | None = None,
        trust: TrustStore | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._probe = probe
        self._log_dir = Path(log_dir) if log_dir is not None else None
        # Public and mutable, like `trust` beside it: the settings dialog
        # changes it while servers are running, and `rotate_if_needed` reads it
        # once per poll, so a new cap applies on the next tick with no restart
        # (LWSM-1018).
        self.max_log_bytes = MAX_LOG_BYTES
        self.trust = trust if trust is not None else TrustStore()
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._registry = _Registry()
        self._stoppers = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="lwsm-stop"
        )

    # -- logging ---------------------------------------------------------

    @property
    def log_dir(self) -> Path:
        """`$XDG_STATE_HOME/localwebservermanager/logs` unless one was injected."""
        if self._log_dir is not None:
            return self._log_dir
        return default_state_dir() / "logs"

    def log_path_for(self, project: Path, name: str) -> Path:
        """`<name>-<hash>.log`, where the hash is of the resolved project path.

        `docs/design.md § Observability` writes this as `<project>.log`. The
        hash is added because the name is scanned or hand-edited text and this
        is a *filename*: two projects called `web` in different scan roots would
        otherwise share one log, and a name containing `/` or `..` would choose
        where the log goes. Sanitising alone fixes the second and not the first.
        """
        slug = _UNSAFE_IN_FILENAME.sub("-", name)[:MAX_LOG_NAME_CHARS] or "project"
        digest = hashlib.sha256(
            str(Path(project).resolve()).encode("utf-8", "surrogateescape")
        ).hexdigest()[:8]
        return self.log_dir / f"{slug}-{digest}.log"

    def _open_log(self, path: Path) -> int:
        """A private regular file, appended to, never followed.

        `applog.py`'s discipline, reused rather than restated: a symlink planted
        at this path would append a hostile project's stdout into any file this
        user owns, a hard link would do the same undetected, and `O_WRONLY` on a
        FIFO blocks until a reader appears — which would hang Start with no
        error and no log line.

        `O_RDWR` rather than `O_WRONLY` because `rotate_if_needed` copies the
        file out through this same descriptor rather than reopening the path,
        and `pread` on a write-only descriptor is `EBADF`. The child inherits it
        as stdout and can therefore read back its own log, which is not a leak —
        it is the project's own output, in the project's own file.
        """
        _prepare_state_dir(path.parent)
        return _open_private_regular(path, os.O_RDWR | os.O_CREAT | os.O_APPEND)

    def rotate_if_needed(self, project: Path) -> bool:
        """One rotation at `max_log_bytes`, keeping the inode.

        Copy-then-truncate rather than rename, because the child holds a
        *duplicate* of this descriptor: renaming the file would leave it writing
        into an unlinked inode, so its output would exist nowhere a reader can
        reach. The cost is a write racing the copy, which is lost — a bounded
        and stated loss, against silently losing everything after the rotation.
        """
        # Everything below works through a DUPLICATE of the log descriptor,
        # taken while the lock proves the entry is still held. `_get` releases
        # the lock the moment it returns, and the `fstat`, `pread` and
        # `ftruncate` then run on the poll thread while a `stop()` on a worker
        # may pop the same entry and have `_reap` close `managed.log_fd`. The
        # kernel reissues a freed number to the very next `open` -- the backup
        # opened a few lines down is itself a candidate -- so the truncate
        # would blank whatever now holds it (LWSM-1169, reproduced). A
        # duplicate names the same open file and is ours alone to close.
        with self._registry.lock:
            managed = self._registry.processes.get(Path(project).resolve())
            if managed is None:
                return False
            fd = os.dup(managed.log_fd)

        try:
            size = os.fstat(fd).st_size
            if size <= self.max_log_bytes:
                return False

            backup = managed.log_path.with_name(managed.log_path.name + ROTATION_SUFFIX)
            # The same open as the log's, and it was NOT until LWSM-1229: this
            # one carried `O_NOFOLLOW` alone, so a FIFO planted here blocked
            # the poll thread forever -- `O_NOFOLLOW` refuses a symlink and
            # says nothing about a pipe.
            #
            # Emptying it is `ftruncate` AFTER the check rather than `O_TRUNC`
            # in the flags, which is not a detail: `O_TRUNC` destroys the
            # target as part of opening it, so on a hard link planted here the
            # file would be blanked and the refusal would arrive too late to
            # matter. The check has to gate the destruction to be worth having.
            out = _open_private_regular(backup, os.O_WRONLY | os.O_CREAT)
            try:
                os.ftruncate(out, 0)
                offset = 0
                while offset < size:
                    # Read through our own descriptor, never by reopening the
                    # path: reopening is a second chance for a symlink to be
                    # swapped in between the check and the copy.
                    chunk = os.pread(fd, _COPY_CHUNK_BYTES, offset)
                    if not chunk:
                        break
                    offset += len(chunk)
                    os.write(out, chunk)
            finally:
                os.close(out)
            os.ftruncate(fd, 0)
            log.info("rotated the log for %s at %d bytes", managed.name, size)
            return True
        finally:
            os.close(fd)

    # -- starting --------------------------------------------------------

    def start(
        self,
        project: Path,
        name: str,
        argv: list[str] | tuple[str, ...],
        port: int | None,
    ) -> ManagedProcess:
        """Spawn `argv` in its own session, with the port pre-flight first.

        Raises `PortAlreadyBound`, `LauncherRefused`, `LauncherUntrusted`,
        `AlreadyRunning`, or `OSError` if the log cannot be opened. A
        `ProbeError` from the pre-flight propagates unchanged: a socket table we
        could not read is not evidence the port is free, and it is not evidence
        it is taken either — the caller decides, and the app log already carries
        the reason.
        """
        resolved_project = Path(project).resolve()
        argv = tuple(argv)
        if not argv:
            raise SupervisorError("cannot start a project with an empty argv")

        # Reserved under the lock, not merely checked. Everything below runs
        # with the lock released, so a bare membership test is a check-then-act
        # (LWSM-1137): two starts both pass it, both spawn, and the second
        # insert overwrites the first `ManagedProcess` — leaking its log
        # descriptor and forgetting the PID that still holds the port, which is
        # verbatim the hazard `AlreadyRunning`'s own docstring names.
        with self._registry.lock:
            if (
                resolved_project in self._registry.processes
                or resolved_project in self._registry.starting
            ):
                raise AlreadyRunning(f"{name} is already running under this manager")
            if resolved_project in self._registry.stopping:
                # Reproduced 2026-08-25: without this a Start arriving inside
                # the grace window spawns a SECOND child, the in-flight stop
                # then kills the old group while the new child holds the port,
                # and `_port_after_stop` reports the manager's own server as
                # one it did not start.
                raise AlreadyRunning(f"{name} is still stopping")
            self._registry.starting.add(resolved_project)

        try:
            # Step 1 of every start, and of every restart (ADR-0003).
            if port is not None and self._probe.snapshot().is_bound(port):
                raise PortAlreadyBound(port)

            launcher = _launcher_path(resolved_project, argv)
            if launcher is not None:
                launcher = validate_launcher(resolved_project, launcher)
            elif not _is_npm_run(argv):
                # Neither a file we can check nor the one shape whose content
                # lives in `package.json`. `bash -x start.sh` and
                # `env node serve.mjs` reach `validate_launcher` nowhere, so
                # the containment, ownership and writability refusals never
                # run and the confirmation binds to argv alone — while the
                # script they name is as untrusted as one named directly.
                # Refusing beats guessing which argument is the file: that is
                # path arithmetic, which `_launcher_path`'s docstring records
                # costing three launcher kinds once already (LWSM-1228).
                raise LauncherRefused(
                    f"{' '.join(argv)} is a launcher shape this manager "
                    "cannot check: it names no file inside the project and "
                    "is not `npm run <script>`"
                )
            fingerprint = launcher_fingerprint(resolved_project, argv)
            if not self.trust.is_confirmed(resolved_project, fingerprint):
                raise LauncherUntrusted(launcher, argv, fingerprint)

            log_path = self.log_path_for(resolved_project, name)
            fd = self._open_log(log_path)
            try:
                managed = self._spawn(resolved_project, name, argv, port, log_path, fd)
            except BaseException:
                os.close(fd)
                raise

            with self._registry.lock:
                self._registry.processes[resolved_project] = managed
        finally:
            # The reservation ends when the entry lands in `processes` or when
            # the start fails — never later. A refused start that kept it would
            # lock the project out for the rest of the session.
            with self._registry.lock:
                self._registry.starting.discard(resolved_project)

        log.info(
            "started %s as pid %d (argv %r, port %s)", name, managed.pid, argv, port
        )
        return managed

    def _spawn(
        self,
        project: Path,
        name: str,
        argv: tuple[str, ...],
        port: int | None,
        log_path: Path,
        fd: int,
    ) -> ManagedProcess:
        popen = subprocess.Popen(  # noqa: S603 - the trust gate above is the check
            list(argv),
            cwd=str(project),
            env=build_child_env(port),
            # A file, not a pipe (ADR-0003): a child holding a pipe dies of
            # SIGPIPE the moment it writes after this manager exits, which would
            # make "children are left running" false in practice.
            stdout=fd,
            stderr=subprocess.STDOUT,
            # Merged output only. A launcher that reads stdin would otherwise
            # block forever on a descriptor nobody is ever going to write to.
            stdin=subprocess.DEVNULL,
            # The whole point: a new session and process group whose id equals
            # the child's PID, so the tree can be signalled and this manager can
            # never signal its own group.
            start_new_session=True,
            close_fds=True,
        )
        # Captured now, while the process is certainly alive, so psutil holds its
        # creation time. That is what makes `_raise_if_pid_reused` able to fire
        # later — a handle built from a scanned PID has nothing to compare.
        handle = psutil.Process(popen.pid)
        return ManagedProcess(
            project=project,
            name=name,
            popen=popen,
            handle=handle,
            log_path=log_path,
            log_fd=fd,
            port=port,
        )

    # -- stopping --------------------------------------------------------

    def stop(
        self,
        project: Path,
        grace: float = GRACE_SECONDS,
        _on_wait: Callable[[], None] | None = None,
    ) -> StopOutcome:
        """SIGTERM the group, wait `grace`, SIGKILL what is left, then reap.

        Every signal goes through a `psutil.Process` handle, never
        `os.killpg(pid, ...)`: psutil's `_send_signal` calls
        `_raise_if_pid_reused()` and raises `NoSuchProcess` where the bare call
        would signal whatever now holds that number. The managed child is not
        reaped until the very end, so its PID cannot be recycled while it is
        still in use as the group id.

        `_on_wait` is a test seam and nothing else: it fires once per turn of
        the wait loop, which is where "did we reap too early?" is observable.
        """
        # Popped here, under the lock, rather than at the end in `_reap`. Two
        # overlapping stops for one project would otherwise both retrieve the
        # same `ManagedProcess` and both reach `_close_quietly(managed.log_fd)`,
        # and the second `os.close` operates on an integer the kernel is free to
        # have reissued — to another project's log, or to the rotation backup
        # (LWSM-1138). Whoever pops owns the sequence; a later caller finds
        # nothing and returns an empty outcome, which is what makes stop()
        # idempotent.
        #
        # Popping is not the same as RESERVING, and only the pop was here
        # (LWSM-1168). Everything below runs with the lock released, so between
        # these two lines and the return the project sits in neither map and a
        # concurrent `start()` passes its pre-flight. The key is therefore held
        # in `stopping` for the whole sequence — `start()`'s reservation read
        # backwards, and discarded in a `finally` for its reason: a stop that
        # raised would otherwise leave the project unstartable for the session.
        #
        # It gates `start()` alone. A second `stop()` still finds nothing and
        # returns an empty outcome, which is what makes stop() idempotent.
        key = Path(project).resolve()
        with self._registry.lock:
            managed = self._registry.processes.pop(key, None)
            if managed is not None:
                self._registry.stopping.add(key)
        if managed is None:
            return StopOutcome()

        try:
            return self._stop_sequence(managed, grace, _on_wait)
        finally:
            with self._registry.lock:
                self._registry.stopping.discard(key)

    def _stop_sequence(
        self,
        managed: ManagedProcess,
        grace: float,
        _on_wait: Callable[[], None] | None,
    ) -> StopOutcome:
        """The signal, wait, escalate and reap half, with the key reserved."""
        members = self._group_members(managed)
        # Pids we were not allowed to signal. `design.md`: "nothing is reported
        # as success that was not verified" — and a `psutil.Error` here was
        # logged at INFO and dropped, so a member the kernel refused left
        # `StopOutcome` looking exactly like a clean stop (LWSM-1224).
        #
        # `NoSuchProcess` is deliberately NOT collected: a member that exited
        # between the enumeration and the signal is the ordinary case and is
        # the outcome we wanted anyway. Reporting it would make every stop
        # noisy, which is how a warning stops being read.
        unsignalled: list[int] = []
        terminated: list[int] = []
        for proc in members:
            try:
                proc.terminate()
                terminated.append(proc.pid)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                log.info("could not signal pid %d: %s", proc.pid, exc)
                unsignalled.append(proc.pid)

        self._wait_for(members, grace, _on_wait)

        # Re-enumerated rather than reusing what `_wait_for` returned. A
        # process that joined the group since the SIGTERM went out — a trap
        # handler that respawns, a watcher, a cluster replacing a worker — is
        # in no list here, so it was signalled by neither phase, survived
        # holding the port, and the outcome came back clean (LWSM-1204).
        # ADR-0003 calls stopping the whole tree "the single most important
        # correctness property of the Stop button", and its own
        # killpg-per-phase prescription does not have this hole.
        #
        # This asks the same question `_group_members` answered before the
        # first signal, so it also still contains everything that ignored the
        # SIGTERM: it is a superset of the survivors, not a different set.
        survivors = self._group_members(managed)

        killed: list[int] = []
        for proc in survivors:
            try:
                proc.kill()
                killed.append(proc.pid)
            except psutil.NoSuchProcess:
                # It died during the grace period, which is the success this
                # phase exists to bring about.
                pass
            except psutil.Error as exc:
                log.info("could not kill pid %d: %s", proc.pid, exc)
                unsignalled.append(proc.pid)
        if killed:
            self._wait_for(survivors, KILL_TIMEOUT_SECONDS, None)

        # And once more, because a process forked during the KILL wait is the
        # same hole one phase along. Nothing is signalled for these: they are
        # reported, the way a still-bound port is (`_port_after_stop`), so a
        # stop that could not finish the job says so instead of claiming it.
        stragglers = [proc.pid for proc in self._group_members(managed)]

        exit_code = self._reap(managed)
        bound, warning = self._port_after_stop(managed)
        if unsignalled:
            refused = ", ".join(str(pid) for pid in sorted(set(unsignalled)))
            refused_warning = (
                f"{managed.name} stopped, but {len(set(unsignalled))} process(es) "
                f"could not be signalled: {refused}"
            )
            warning = (
                refused_warning if warning is None else f"{warning}; {refused_warning}"
            )
        if stragglers:
            straggler_warning = (
                f"{managed.name} stopped, but {len(stragglers)} process(es) in "
                f"its group were still running afterwards: {stragglers}"
            )
            warning = (
                straggler_warning
                if warning is None
                else f"{warning}; {straggler_warning}"
            )
        log.info(
            "stopped %s: terminated %r, killed %r, exit %s",
            managed.name,
            terminated,
            killed,
            exit_code,
        )
        return StopOutcome(
            terminated=tuple(terminated),
            killed=tuple(killed),
            exit_code=exit_code,
            port_still_bound=bound,
            warning=warning,
        )

    def stop_async(
        self,
        project: Path,
        grace: float = GRACE_SECONDS,
        _on_wait: Callable[[], None] | None = None,
    ) -> Future[StopOutcome]:
        """`stop` on a worker thread. A 5-second wait on the UI thread freezes it."""
        return self._stoppers.submit(self.stop, project, grace, _on_wait)

    def owns_pid(self, project: Path, pid: int) -> bool:
        """Whether `pid` sits in the process group of our child for `project`.

        The GROUP, not the pid, and for `_group_members`' reason inverted: a
        launcher that double-forks leaves the actual server reparented to init,
        so the process holding the port is usually a grandchild. Comparing
        against the child's own pid would report every wrapper-script project as
        not ours. `start_new_session=True` guarantees the whole tree shares the
        child's pid as its group id, and it is the same group `stop()` signals,
        so the two cannot disagree about what counts as ours.

        `os.getpgid` rather than `_group_members`, which walks every process on
        the machine: this is asked once per project per poll and the question is
        about ONE pid.

        **`_alive` is not belt-and-braces, it is the PID-reuse guard.** A dead
        child's pid is free to be reallocated as some unrelated process's group
        id, at which point a bare `getpgid` comparison would call a stranger
        ours. The handle captured at spawn carries the `create_time` that tells
        them apart -- ADR-0004: "for a *managed* server, identity is the
        recorded child PID **plus its `create_time`**, never the working
        directory".

        Deliberately NOT gated on `exited()`. That reports the LAUNCHER is gone,
        and LWSM-1165 keeps the registry entry while the group lives precisely
        because a `start.sh` that forks and exits leaves the server running --
        so gating here would report exactly that project as not ours.
        """
        managed = self._get(project)
        if managed is None or not _alive(managed.handle):
            return False
        try:
            return os.getpgid(pid) == managed.pid
        except OSError:
            # ProcessLookupError for a holder that exited between the snapshot
            # and this call, which is the ordinary race and not ours by
            # definition. Widened to OSError because a hardened kernel can
            # refuse the query, and a refusal is not evidence of ownership.
            return False

    def _group_members(self, managed: ManagedProcess) -> list[psutil.Process]:
        """Every live process in the child's process group.

        The group, not the descendants: a launcher that double-forks leaves a
        server reparented to init, which `Process.children()` can no longer see
        while `start_new_session=True` guarantees it is still in this group.
        That is the wrapper-script case LWSM-1009's acceptance names.
        """
        pgid = managed.pid
        if pgid == os.getpgrp():
            # Unreachable while start_new_session=True holds, and checked anyway:
            # if it ever stopped holding, this function would signal the manager.
            raise SupervisorError(
                f"refusing to signal process group {pgid}, which is our own"
            )

        members: list[psutil.Process] = []
        seen: set[int] = set()
        for proc in psutil.process_iter():
            try:
                if os.getpgid(proc.pid) != pgid:
                    continue
            except (OSError, psutil.Error):
                continue
            members.append(proc)
            seen.add(proc.pid)
        if managed.pid not in seen:
            members.append(managed.handle)
        return [proc for proc in members if _alive(proc)]

    def _wait_for(
        self,
        procs: list[psutil.Process],
        timeout: float,
        _on_wait: Callable[[], None] | None,
    ) -> list[psutil.Process]:
        """Poll until nothing in `procs` is alive or `timeout` elapses.

        Polling rather than `psutil.wait_procs`, which *reaps* a process that is
        our own child — and reaping the managed child before the sequence ends
        is the thing ADR-0003 forbids.
        """
        deadline = self._clock() + timeout
        while True:
            if _on_wait is not None:
                _on_wait()
            survivors = [proc for proc in procs if _alive(proc)]
            if not survivors or self._clock() >= deadline:
                return survivors
            self._sleep(POLL_INTERVAL_SECONDS)

    def _reap(self, managed: ManagedProcess) -> int | None:
        """Collect the child's exit status, last, and release its log."""
        try:
            exit_code = managed.popen.wait(timeout=KILL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log.warning(
                "%s did not exit after SIGKILL; leaving it unreaped", managed.name
            )
            exit_code = None
        # No registry pop here: both callers took the entry first — `stop()`
        # before it signalled anything (LWSM-1138), `reap_exited` before it
        # reaped (LWSM-1165) — so this descriptor is one nothing else can still
        # reach and closing it cannot be done twice.
        _close_quietly(managed.log_fd)
        return exit_code

    def _port_after_stop(self, managed: ManagedProcess) -> tuple[bool, str | None]:
        """A bound port after a stop is a warning, never a second signal.

        ADR-0003: the `or` this replaces fired exactly when our child was
        already gone and something *else* held the port — the everyday
        `running (wrong port)` case — and then signalled a number the kernel was
        free to have reissued.
        """
        if managed.port is None:
            return False, None
        try:
            bound = self._probe.snapshot().is_bound(managed.port)
        except ProbeError as exc:
            return False, f"could not check port {managed.port} after stopping: {exc}"
        if not bound:
            return False, None
        # Says WHAT was observed, never whose the holder is. Nothing here asks
        # the kernel who owns the socket, and since LWSM-1204 the honest answer
        # may be a straggler of our own that the sweep reported a line earlier
        # (LWSM-1225). `design.md` asks for the port to be reported as held by
        # a process the user cannot inspect, rather than for an owner to be
        # invented.
        return True, (
            f"{managed.name} stopped, but port {managed.port} is still bound; "
            "nothing was signalled for whatever holds it"
        )

    def reap_exited(self) -> dict[Path, int | None]:
        """Drop every entry whose process group is entirely gone (LWSM-1165).

        Only `start()` inserted and only `stop()` popped, so a launcher that
        died by itself — a missing dependency, a bad `scripts.dev`, an ordinary
        crash — kept its slot for the life of the session. The port was free,
        so the UI showed STOPPED and disabled Stop and Restart, while every
        Start raised `AlreadyRunning`: no route back. Its log descriptor was
        never closed either. LWSM-1134 fixed the overlay symptom and left this.

        **The launcher being gone is not enough, and that is the whole shape of
        this method.** A `start.sh` that spawns a server and exits leaves the
        server alive in the same process group — the double-forking wrapper
        `_group_members` exists for. `stop()` signals the group *through this
        entry*, so dropping it there would orphan a running server behind a
        greyed-out Stop button, which is worse than the defect. The cheap
        `_alive` check only selects a candidate; the group decides.

        Cheap first for a real reason: `_group_members` walks every process on
        the machine, and this runs once a poll. On an ordinary tick the launcher
        is alive and nothing past the first check happens.

        Popping under the lock and by IDENTITY, for `stop()`'s reason: whoever
        pops owns the sequence, so a project a concurrent `stop()` already took
        is left entirely alone rather than reaped twice (LWSM-1138).
        """
        collected: dict[Path, int | None] = {}
        for project, managed in self.running().items():
            if _alive(managed.handle):
                continue
            if self._group_members(managed):
                continue
            with self._registry.lock:
                if self._registry.processes.get(project) is not managed:
                    continue
                del self._registry.processes[project]
            collected[project] = self._reap(managed)
            log.info(
                "%s exited on its own (exit %s); releasing its slot",
                managed.name,
                collected[project],
            )
        return collected

    # -- lifetime --------------------------------------------------------

    def _get(self, project: Path) -> ManagedProcess | None:
        with self._registry.lock:
            return self._registry.processes.get(Path(project).resolve())

    def running(self) -> dict[Path, ManagedProcess]:
        with self._registry.lock:
            return dict(self._registry.processes)

    def is_stopping(self, project: Path) -> bool:
        """Whether a stop is in flight for this project (LWSM-1191).

        `stop()` holds the key from before it signals anything until the
        sequence returns, which is the window in which `start()` refuses. The
        UI needs the same fact to stop OFFERING a Start it knows will be
        refused, and asking here is what keeps the two answers one answer —
        the alternative was inferring it from the derived status, which cannot
        see a reservation at all.

        Neither `running()` nor `exited()` answers it: the entry is popped
        before the sequence begins, so a stopping project is in neither map.
        """
        with self._registry.lock:
            return Path(project).resolve() in self._registry.stopping

    def exited(self, project: Path) -> bool:
        """Whether a child we spawned is gone — asked WITHOUT reaping it.

        `Popen.poll()` would answer this in one line and must not be used: it
        reaps, which frees the PID that `start_new_session=True` made the
        process-group id, and ADR-0003 forbids reaping until the stop sequence
        ends for exactly that reason. `_alive` is the non-reaping form already
        used by the stop sequence — a zombie counts as exited here while
        remaining unreaped, which is the state that keeps the PID reserved.

        False for a project this manager never started: there is nothing of
        ours to have exited, and `running()` is the question about that.

        `running()` cannot answer this, and that is still true: an entry is
        removed by whoever pops it — `stop()`, or `reap_exited` on the next poll
        — so between a child exiting and the tick that notices, it is still in
        the map. This is the question that closes that window, and it is what
        let a failed start sit at `starting` for the life of the session
        (LWSM-1134). The docstring said the removal happened in `_reap` until
        LWSM-1165; the pop has been in `stop()` since LWSM-1138.
        """
        managed = self._get(project)
        if managed is None:
            return False
        return not _alive(managed.handle)

    def close(self) -> None:
        """Release our descriptors and threads, and **leave the servers running**.

        ADR-0003: children outlive the manager by design, and ADR-0004 lets a
        later session re-adopt them by probing. Stopping them here would make
        Quit a destructive action nobody asked for.
        """
        self._stoppers.shutdown(wait=True)
        with self._registry.lock:
            managed_list = list(self._registry.processes.values())
            self._registry.processes.clear()
        for managed in managed_list:
            # Reap the ones that have already exited so the status is collected
            # rather than left to the interpreter's exit-time warning; a still
            # running one is deliberately left alone.
            managed.popen.poll()
            _close_quietly(managed.log_fd)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
