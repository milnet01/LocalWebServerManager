"""Spawning and reaping the servers this manager starts.

Core module — no Qt at all, not even QtCore (`docs/standards/coding-overrides.md § O1`),
like `ports.py`. Stop needs a worker thread and a plain `ThreadPoolExecutor` is
enough for one; making this a `QObject` would put a Qt dependency into the one
module that spawns processes for a living.

Contract: [`ADR-0003`](../../docs/decisions/0003-launch-via-project-scripts.md),
`docs/design.md § Observability` for the log files, and ADR-0006 for
`LWSM_MANAGED`. Two security rules live here: process handles are signalled,
never bare PIDs (LWSM-1047), and the child environment is an allowlist
(LWSM-1048). The third, that a discovered launcher is untrusted until
confirmed (LWSM-1046), is `trust.py`'s; `start()` calls its gate.

**What this module does NOT do.** It does not show the confirmation dialog
(LWSM-1010 owns the UI), does not drive systemd units (LWSM-1028), does not
tail the log into a `LogBuffer` (`logbuffer.py`, LWSM-1015), and does not write a
confirmation into the registry — `stores.TrustStore` keeps its own small
file, `trust.json`, beside `settings.json` (LWSM-1046). Each of those is a named
item, not an oversight.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from lwsm.applog import (
    default_state_dir,
    get_logger,
    open_private_regular,
    prepare_state_dir,
)
from lwsm.ports import ProbeError, SupportsSnapshot
from lwsm.settings import DEFAULT_LOG_MAX_MIB
from lwsm.stores import StartedEntry, StartedStore, TrustStore
from lwsm.trust import (
    LauncherRefused,
    LauncherUntrusted,
    SupervisorError,
    bounded_regular_bytes,
    is_npm_run,
    launcher_fingerprint,
    launcher_path,
    npm_material,
    npm_shown,
    validate_launcher,
)

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
        "XAUTHORITY",
        "WAYLAND_DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
    }
)

# `LC_*` is a family, not a name: `LC_ALL`, `LC_TIME`, `LC_NUMERIC` and six more
# all change how a server formats output. A prefix rather than nine entries.
ENV_ALLOW_PREFIXES = ("LC_",)

# How long the once-per-supervisor check that the user manager can run a scope
# may take. It runs on the first start, on the thread that asked for it.
SCOPE_PROBE_TIMEOUT_SECONDS = 2.0

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


_COPY_CHUNK_BYTES = 1 << 20

# A project name reaches a filename here, and it is hand-edited or scanned text.
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
MAX_LOG_NAME_CHARS = 64


class PortAlreadyBound(SupervisorError):
    """The pre-flight check found something already listening on the port.

    Step 1 of every start (`docs/design.md`), and of every restart, since
    ADR-0003 defines restart as "stop then start *with the same pre-flight
    check*". The controller turns it into the conflict warning (LWSM-1013).

    `holder` is the PID the same snapshot names on the port, or None when it
    names none: another user's process (ADR-0004), a listener on a network
    address only, or two listeners on one port.
    """

    def __init__(self, port: int, holder: int | None = None):
        super().__init__(f"port {port} is already bound")
        self.port = port
        self.holder = holder


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
    """One child this supervisor spawned, and the handles that identify it.

    `popen` is None for a server adopted after a relaunch (LWSM-1428): it is
    no longer this process's child, so there is nothing to wait on.
    """

    project: Path
    name: str
    popen: subprocess.Popen[bytes] | None
    handle: psutil.Process
    log_path: Path
    log_fd: int
    port: int | None
    # Adopted entries only: the boot-clock moment the group was last seen
    # occupied by a process we can vouch for (LWSM-1494, `_vouched`).
    vouched_at: float | None = None

    @property
    def pid(self) -> int:
        """Also the process-group id: `start_new_session=True` guarantees it."""
        return self.handle.pid


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
    # A launcher and everything it runs resolve commands against PATH. Where
    # the manager itself was started without one, the child gets the system
    # default rather than none (known-issue-056, LWSM-1321).
    #
    # Only ABSOLUTE entries survive. `Popen` resolves a bare `argv[0]` against
    # this PATH after changing into the project, so an empty entry, `.` or
    # `node_modules/.bin` would make `npm`, `python3` or `node` name a file
    # inside the project that the trust gate never read (review-code
    # 2026-10-01).
    absolute = [
        entry for entry in env.get("PATH", "").split(os.pathsep) if os.path.isabs(entry)
    ]
    env["PATH"] = os.pathsep.join(absolute) if absolute else os.defpath
    if port is not None:
        env["PORT"] = str(port)
    # ADR-0006: a presentation hint with no security value. It is unauthenticated
    # and trivially forged, so nothing may be granted or skipped on the strength
    # of it — this is the only place this project sets it.
    env["LWSM_MANAGED"] = "1"
    return env


def scope_prefix(
    env: Mapping[str, str], *, run: object = None, which: object = None
) -> tuple[str, ...]:
    """The argv prefix that puts a server in its own systemd scope, or `()`.

    ADR-0003 leaves servers running when the manager exits, and inside this
    process that holds. What broke it is outside (LWSM-1420): Plasma runs a
    desktop launch as a transient `app-…@<uuid>.service` with
    `KillMode=control-group`, so when `lwsm` exits systemd kills everything
    left in its cgroup, and `start_new_session=True` changes the session, not
    the cgroup. `systemd-run --scope` moves the server into a scope of its own
    and then execs it in place, so the PID `Popen` holds, the process group
    and the psutil handle are all still the server's.

    Checked by running `true` the same way, rather than assumed from
    `systemd-run` existing: with no user manager to talk to it fails before
    the exec, and every start would then fail with it. `()` means a plain
    launch, which is what this did before and still right where no unit
    exists to kill the server. A failed check logs its cause at WARNING
    (LWSM-1446): a server launched plainly under Plasma dies on Quit, and
    the log is the only place the user can learn why.
    """
    # Looked up on the CHILD's PATH, which holds only absolute entries, and
    # refused unless absolute: `Popen(cwd=project)` resolves a relative answer
    # inside each project, which is the hole `build_child_env` closes for
    # `argv[0]` (LWSM-1440).
    if which is not None:
        executable = which("systemd-run")  # type: ignore[operator]
    else:
        executable = shutil.which("systemd-run", path=env.get("PATH", os.defpath))
    if not executable or not os.path.isabs(executable):
        log.info("no absolute systemd-run on PATH; launching without a scope")
        return ()
    prefix = (executable, "--user", "--scope", "--quiet", "--collect", "--")
    runner = run if run is not None else subprocess.run
    try:
        completed = runner(  # type: ignore[operator]
            [*prefix, "true"],
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=SCOPE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("launching without a systemd scope: the check failed: %s", exc)
        return ()
    status = getattr(completed, "returncode", 1)
    if status != 0:
        log.warning(
            "launching without a systemd scope: the check exited with status %s",
            status,
        )
        return ()
    return prefix


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

    `foreign.py` asks this, through `wait_until_gone`, about processes that are
    not our children. A zombie there is someone else's to reap, and just as gone.
    """
    try:
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.AccessDenied:
        # Running, but its status cannot be read (hidepid, an LSM). Counting it
        # as dead let the stop loop give up early on a process that is still
        # there; counting it as alive costs at most the rest of the wait
        # (known-issue-056, LWSM-1321).
        return True
    except psutil.Error:
        return False
    except OSError:
        # `Process.status()` reads /proc; hidepid, an LSM or a vanished entry
        # raise plain OSError, which psutil.Error does not cover (the shape
        # `ports.py` documents for `net_connections`).
        return False


def wait_until_gone(
    procs: list[psutil.Process],
    timeout: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    on_wait: Callable[[], None] | None = None,
) -> list[psutil.Process]:
    """Poll until nothing in `procs` is alive or `timeout` elapses; return
    the survivors. `on_wait`, where given, runs before each look.

    The one polling loop for the managed stop and `foreign.py`'s stop.
    Polling rather than `psutil.wait_procs`, which *reaps* a process that is
    our own child — and reaping the managed child before the sequence ends
    is the thing ADR-0003 forbids.
    """
    deadline = clock() + timeout
    while True:
        if on_wait is not None:
            on_wait()
        survivors = [proc for proc in procs if _alive(proc)]
        if not survivors or clock() >= deadline:
            return survivors
        sleep(POLL_INTERVAL_SECONDS)


# psutil reads a start time in clock ticks (1/100 s on Linux), rounded down,
# so a process started up to one tick after a moment can read as started at it.
START_TIME_RESOLUTION_SECONDS = 0.01


def _boot_clock() -> float:
    """Seconds since boot, suspend included: the clock a start time is read on."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def _started_since_boot(proc: psutil.Process) -> float:
    """`proc`'s start on `_boot_clock`, which no clock step moves.

    psutil adds `/proc/stat`'s boot time to the kernel's ticks since boot, and
    taking the boot time away again undoes that. Rounded to the tick, so the
    same process gives the same value whatever the boot time read (LWSM-1448).
    A clock step landing between the two reads is not covered.
    """
    return round(proc.create_time() - psutil.boot_time(), 2)


def _boot_id() -> str | None:
    """This boot's id, or None where the kernel does not say (LWSM-1448)."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as f:
            return f.read().strip() or None
    except (OSError, ValueError):
        return None


def _identity_refusal(entry: StartedEntry, handle: psutil.Process) -> str:
    """Why `handle` is not the process `entry` recorded, or "" if it is.

    Off the wall clock where the entry allows (LWSM-1448): psutil's
    `create_time` moves with a clock step, so comparing it read our own server
    as a reused PID. An entry from before `since_boot` still compares it, and a
    mismatch there is a reused PID or a clock stepped between sessions.
    """
    if entry.since_boot is None:
        if handle.create_time() != entry.create_time:
            return "pid %d has another create_time, so it is not the one started"
        return ""
    if entry.boot_id != _boot_id():
        return "the machine has restarted since pid %d was started"
    if _started_since_boot(handle) != entry.since_boot:
        return "pid %d started at another time, so it is not the one started"
    return ""


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
    # Processes still in a project's group after its stop's SIGKILL wait
    # (known-issue-040, LWSM-1321). A process in uninterruptible sleep outlives
    # SIGKILL for as long as its I/O takes, and forgetting it let the next
    # `start()` spawn a second server beside one that could still hold the
    # port. `start()` refuses while any is alive and drops them once none is.
    stragglers: dict[Path, list[psutil.Process]] = field(default_factory=dict)
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
        started: StartedStore | None = None,
    ) -> None:
        self._probe = probe
        # What this manager started, so a relaunch can take it back (LWSM-1428).
        self.started = started if started is not None else StartedStore()
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
        # `scope_prefix`'s answer once it succeeds. A failure is not kept: it
        # is asked again at the next start (LWSM-1446, ADR-0003).
        self._scope: tuple[str, ...] | None = None
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
        prepare_state_dir(path.parent)
        return open_private_regular(path, os.O_RDWR | os.O_CREAT | os.O_APPEND)

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
            return self._rotate_through(fd, managed.log_path, managed.name)
        finally:
            os.close(fd)

    def rotate_log_at(self, project: Path, name: str) -> bool:
        """`rotate_if_needed` for a log this session holds no descriptor for.

        Servers outlive the manager (ADR-0003), so after a Quit, or for one
        re-adopted after a relaunch, nothing here held its log and it grew
        without the cap `design.md § Observability` promises (review-code
        2026-10-01 L3-M5). Opened by path with `_open_log`'s discipline; the
        child's `O_APPEND` makes truncating under it safe. A project this
        session is running is skipped, since `rotate_if_needed` owns it.
        """
        resolved = Path(project).resolve()
        with self._registry.lock:
            if resolved in self._registry.processes:
                return False
        log_path = self.log_path_for(resolved, name)
        try:
            fd = open_private_regular(log_path, os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            return self._rotate_through(fd, log_path, name)
        finally:
            os.close(fd)

    def _rotate_through(self, fd: int, log_path: Path, name: str) -> bool:
        """The copy-then-truncate itself, through a descriptor the caller owns."""
        size = os.fstat(fd).st_size
        if size <= self.max_log_bytes:
            return False

        backup = log_path.with_name(log_path.name + ROTATION_SUFFIX)
        # The copy goes to a NEW file that replaces the backup only once it is
        # complete (review-code 2026-10-08 L01-L3). Emptying the backup in
        # place first lost the previous rotation whenever the copy failed --
        # a full disk, every tick. `mkstemp` creates exclusively and private,
        # so nothing planted can be opened in its place, and the rename
        # replaces whatever sits at the backup's name without following or
        # emptying it: a FIFO, a symlink or a hard link there is unlinked,
        # never written through (what LWSM-1229 guarded by refusing them).
        out, tmp_name = tempfile.mkstemp(
            dir=log_path.parent, prefix=backup.name + ".", suffix=".tmp"
        )
        try:
            # Only the newest `max_log_bytes` (L01-M1): a log nothing capped --
            # a server left running while the manager was closed -- can be
            # gigabytes, and copying all of it needs that much disk again and
            # leaves a backup far over the cap.
            offset = max(0, size - self.max_log_bytes)
            while offset < size:
                # Read through our own descriptor, never by reopening the
                # path: reopening is a second chance for a symlink to be
                # swapped in between the check and the copy.
                chunk = os.pread(fd, _COPY_CHUNK_BYTES, offset)
                if not chunk:
                    break
                offset += len(chunk)
                # Until every byte is taken (LWSM-1274): a regular file may
                # accept fewer than offered, and the original is emptied
                # below, so a dropped remainder would be gone for good.
                pending = memoryview(chunk)
                while pending:
                    written = os.write(out, pending)
                    if written == 0:
                        # Never spin the poll thread on a write that takes
                        # nothing; refuse and leave the original alone.
                        raise OSError(errno.ENOSPC, "rotation copy made no progress")
                    pending = pending[written:]
        except BaseException:
            os.close(out)
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        os.close(out)
        try:
            os.replace(tmp_name, backup)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
        os.ftruncate(fd, 0)
        log.info("rotated the log for %s at %d bytes", name, size)
        return True

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
        `AlreadyRunning`, or `OSError` if the log cannot be opened or the
        launcher cannot be executed (`Popen` raises it for a missing or
        non-executable file, or an unrecognised binary format). A
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
            left = [
                proc
                for proc in self._registry.stragglers.pop(resolved_project, [])
                if _alive(proc)
            ]
            if left:
                self._registry.stragglers[resolved_project] = left
                pids = ", ".join(str(proc.pid) for proc in left)
                raise AlreadyRunning(
                    f"{name}: {len(left)} process(es) survived the last stop and "
                    f"are still running: {pids}"
                )
            self._registry.starting.add(resolved_project)

        try:
            # Step 1 of every start, and of every restart (ADR-0003).
            if port is not None:
                snapshot = self._probe.snapshot()
                if snapshot.is_bound(port):
                    raise PortAlreadyBound(port, snapshot.holder(port))

            launcher = launcher_path(resolved_project, argv)
            if launcher is not None:
                launcher = validate_launcher(resolved_project, launcher)
                # Unreadable is refused, as for npm below: a file we may run
                # but not read fingerprinted as its argv alone, so one
                # confirmation outlived every later rewrite (LWSM-1509).
                if bounded_regular_bytes(launcher) is None:
                    raise LauncherRefused(
                        f"{launcher} is unreadable, so a change to it could "
                        "not re-arm the trust gate"
                    )
            elif is_npm_run(argv):
                # The untrusted content of this shape is `package.json`, so it
                # meets the same refusals a launcher file does: rewritable by
                # another account, owned by one, or outside the project
                # (review-code 2026-10-01). The return is discarded — `launcher`
                # stays None, which is what tells the dialog no file was named.
                validate_launcher(resolved_project, resolved_project / "package.json")
                # npm reads it too, and it changes what runs (LWSM-1363).
                if os.path.lexists(resolved_project / ".npmrc"):
                    validate_launcher(resolved_project, resolved_project / ".npmrc")
                # Unreadable is refused, never offered: as a fingerprint it was
                # a constant, so one confirmation covered whatever the manifest
                # said afterwards (LWSM-1364).
                if npm_material(resolved_project, argv) is None:
                    raise LauncherRefused(
                        f"package.json has no readable `{argv[2]}` script, or "
                        "a script or .npmrc around it could not be read"
                    )
            else:
                # Neither a file we can check nor the one shape whose content
                # lives in `package.json`. `bash -x start.sh` and
                # `env node serve.mjs` reach `validate_launcher` nowhere, so
                # the containment, ownership and writability refusals never
                # run and the confirmation binds to argv alone — while the
                # script they name is as untrusted as one named directly.
                # Refusing beats guessing which argument is the file: that is
                # path arithmetic, which `launcher_path`'s docstring records
                # costing three launcher kinds once already (LWSM-1228).
                raise LauncherRefused(
                    f"{' '.join(argv)} is a launcher shape this manager "
                    "cannot check: it names no file inside the project and "
                    "is not `npm run <script>`"
                )
            fingerprint = launcher_fingerprint(resolved_project, argv)
            if not self.trust.is_confirmed(resolved_project, fingerprint):
                raise LauncherUntrusted(
                    launcher, argv, fingerprint, npm_shown(resolved_project, argv)
                )

            log_path = self.log_path_for(resolved_project, name)
            fd = self._open_log(log_path)
            try:
                managed = self._spawn(resolved_project, name, argv, port, log_path, fd)
            except BaseException:
                os.close(fd)
                raise

            with self._registry.lock:
                self._registry.processes[resolved_project] = managed
            self._record(managed)
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
        env = build_child_env(port)
        scope = self._scope
        if scope is None:
            # Only a success is remembered: a check that failed once (the user
            # manager not answering yet, say) would otherwise leave every later
            # server in the session unscoped (LWSM-1446).
            scope = scope_prefix(env)
            if scope:
                self._scope = scope
                log.info("launching servers in their own systemd scopes")
        popen = subprocess.Popen(  # noqa: S603 - the trust gate above is the check
            [*scope, *argv],
            cwd=str(project),
            env=env,
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
        try:
            handle = psutil.Process(popen.pid)
        except BaseException:
            # A child with no handle is registered nowhere and nothing could
            # stop it (L3-L3). Its group was created a line ago and is
            # entirely ours, and `popen` is the live handle to its leader, so
            # this is not the bare-PID signal ADR-0003 forbids.
            with contextlib.suppress(OSError):
                os.killpg(popen.pid, signal.SIGKILL)
            try:
                popen.wait(timeout=KILL_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # Stuck past SIGKILL (LWSM-1524), as `_reap` finds one: an
                # unbounded wait here would hold this start for good.
                threading.Thread(
                    target=popen.wait, name="lwsm-late-reap", daemon=True
                ).start()
            raise
        return ManagedProcess(
            project=project,
            name=name,
            popen=popen,
            handle=handle,
            log_path=log_path,
            log_fd=fd,
            port=port,
        )

    # -- across a relaunch (LWSM-1428) -----------------------------------

    def _record(self, managed: ManagedProcess) -> None:
        """Write a started child to the record a later session adopts from."""
        try:
            created = managed.handle.create_time()
        except psutil.Error:
            # Exited already: there is nothing a later session could adopt.
            return
        try:
            since_boot = _started_since_boot(managed.handle)
        except psutil.Error:
            return
        except (OSError, RuntimeError) as exc:
            # `psutil.boot_time()` raises RuntimeError when /proc/stat has no
            # `btime` line. The server is running and registered, so a failed
            # Start would lie; record it by `create_time` alone, as an entry
            # from before LWSM-1448 is (LWSM-1524).
            log.warning("no boot-relative start time for %s: %s", managed.name, exc)
            since_boot = None
        boot_id = _boot_id() if since_boot is not None else None
        self.started.add(
            StartedEntry(
                managed.project,
                managed.name,
                managed.pid,
                created,
                managed.port,
                since_boot if boot_id is not None else None,
                boot_id,
            )
        )

    def adopt(self) -> frozenset[Path]:
        """Take back the servers an earlier session started; run once, at launch.

        An entry is ours only if its PID still names the process it named, by
        `create_time`, and that process still leads the group it was started
        in (LWSM-1428 § 4.3). Anything else is dropped and stays foreign, the
        safe direction. Returns the projects taken back.
        """
        taken: set[Path] = set()
        dropped: list[Path] = []
        for entry in self.started.entries():
            managed = self._adoptable(entry)
            if managed is None:
                dropped.append(entry.project)
                continue
            with self._registry.lock:
                # A start or stop in flight owns the key as `processes` does:
                # a start would overwrite this entry at its insert and leak the
                # descriptor opened here (LWSM-1442).
                reserved = (
                    entry.project in self._registry.starting
                    or entry.project in self._registry.stopping
                )
                held = (
                    None
                    if reserved
                    else self._registry.processes.setdefault(entry.project, managed)
                )
            if held is not managed:
                # Started, starting or stopping this session already, so the
                # record is that start's.
                _close_quietly(managed.log_fd)
                continue
            taken.add(entry.project)
            log.info(
                "adopted %s, pid %d, from an earlier session", entry.name, entry.pid
            )
        self.started.remove(*dropped)
        return frozenset(taken)

    def _adoptable(self, entry: StartedEntry) -> ManagedProcess | None:
        # Each refusal says which check failed (LWSM-1443).
        # Read before the checks: the leader passing them proves the group
        # occupied at this moment (`_vouched`).
        checked_at = _boot_clock()
        try:
            handle = psutil.Process(entry.pid)
            why = _identity_refusal(entry, handle)
            if not why and os.getpgid(entry.pid) != entry.pid:
                why = "pid %d no longer leads its own process group"
        except (psutil.Error, OSError):
            log.info("not adopting %s: pid %d no longer runs", entry.name, entry.pid)
            return None
        if why:
            log.info("not adopting %s: " + why, entry.name, entry.pid)
            return None
        log_path = self.log_path_for(entry.project, entry.name)
        try:
            fd = self._open_log(log_path)
        except OSError as exc:
            # `start()` refuses on the same failure, so a log this session
            # cannot open is a server it could not have started either.
            log.warning(
                "not adopting %s: its log cannot be opened: %s", entry.name, exc
            )
            return None
        return ManagedProcess(
            project=entry.project,
            name=entry.name,
            popen=None,
            handle=handle,
            log_path=log_path,
            log_fd=fd,
            port=entry.port,
            vouched_at=checked_at,
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
            try:
                members = self._group_members(managed)
                # Only once the stop will go ahead, and inside the `try` whose
                # `finally` releases `stopping`: removed before the enumeration,
                # a failure there put the entry back with its record already
                # gone, and the next launch showed the live server as foreign
                # (LWSM-1438).
                self.started.remove(key)
            except Exception:
                # Nothing has been signalled yet and the entry was popped
                # above. Put it back, or the child is forgotten and its log
                # descriptor leaks (LWSM-1274). Any error, not only the
                # self-group `SupervisorError`: an `OSError` from enumerating
                # the group lost the child the same way (review-code
                # 2026-10-01 L3-L2). Only HERE — after the first signal the
                # child may be dead and reaped, and putting it back would lock
                # the project out of `start()`.
                with self._registry.lock:
                    self._registry.processes[key] = managed
                raise
            return self._stop_sequence(key, managed, members, grace, _on_wait)
        finally:
            with self._registry.lock:
                self._registry.stopping.discard(key)

    def _stop_sequence(
        self,
        key: Path,
        managed: ManagedProcess,
        members: list[psutil.Process],
        grace: float,
        _on_wait: Callable[[], None] | None,
    ) -> StopOutcome:
        """The signal, wait, escalate and reap half, with the key reserved.

        `members` is the group as enumerated before the first signal.
        """
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

        try:
            killed, stragglers = self._escalate(
                key, managed, members, grace, _on_wait, unsignalled
            )
        except BaseException:
            # The entry was popped before the first signal and is not put back
            # (`stop()` says why), so nothing else will ever reap this child or
            # close its log: do both on the way out (review-code 2026-10-08
            # L01-L4).
            #
            # And keep whatever we signalled that is still alive as a
            # straggler, while `stopping` still holds the key: with the entry
            # popped and its record gone, `start()` otherwise passed its
            # pre-flight and spawned beside a group still running (LWSM-1441).
            left = [proc for proc in members if _alive(proc)]
            if left:
                with self._registry.lock:
                    self._registry.stragglers[key] = left
            self._reap(managed)
            raise

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

    def _escalate(
        self,
        key: Path,
        managed: ManagedProcess,
        members: list[psutil.Process],
        grace: float,
        _on_wait: Callable[[], None] | None,
        unsignalled: list[int],
    ) -> tuple[list[int], list[int]]:
        """Wait out the grace, SIGKILL what is left, and record stragglers.

        Returns the pids killed and the pids still in the group afterwards.
        Appends to `unsignalled` what the kernel would not let us kill.

        `foreign.stop_tree` runs the same escalation over a fixed set of
        processes; a change to the sequence or its timing belongs in both.
        """
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
        left = self._group_members(managed)
        stragglers = [proc.pid for proc in left]
        if left:
            # Recorded while `stop()` still holds the key in `stopping`, so no
            # `start()` can slip between the two.
            with self._registry.lock:
                self._registry.stragglers[key] = left

        return killed, stragglers

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

        **`is_running()` is not belt-and-braces, it is the PID-reuse guard.** A
        dead child's pid is free to be reallocated as some unrelated process's group
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
        if managed is None:
            return False
        # The PID-reuse guard is `is_running()`, which checks `create_time` and
        # counts a ZOMBIE as running. That is the point: a wrapper launcher
        # that exited stays an unreaped zombie while the server it left lives,
        # and an unreaped pid cannot be reused, so the group is still ours
        # (review-code 2026-10-01). `_alive` here called that server a
        # stranger's. The dead launcher's OWN pid holds nothing, so it alone
        # still needs `_alive`.
        #
        # Not for an ADOPTED leader (`popen is None`, LWSM-1437): its new
        # parent reaps it the moment it exits, so `is_running()` turns False
        # while the server it left still runs in the group. There the guard is
        # the kernel's: a PID in use as a process-group id is not reissued
        # while any member lives (LWSM-1428 § 4.4). That guard ends with the
        # group, and `reap_exited` drops the entry only on its next tick, so
        # once the leader is gone the group is walked and vouched for
        # (`_vouched`, LWSM-1494) rather than judged by its id.
        if managed.popen is None and not self._leader_alive(managed):
            return any(proc.pid == pid for proc in self._group_members(managed))
        if managed.popen is not None:
            try:
                if not managed.handle.is_running():
                    return False
            except psutil.Error:
                return False
        if pid == managed.pid and not _alive(managed.handle):
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
        checked_at = _boot_clock()
        if pgid == os.getpgrp():
            # Unreachable while start_new_session=True holds, and checked anyway:
            # if it ever stopped holding, this function would signal the manager.
            raise SupervisorError(
                f"refusing to signal process group {pgid}, which is our own"
            )

        # Filtered on the pid before a `Process` is built: `process_iter`
        # constructs (and re-validates) one for every process on the machine,
        # and this runs on every upkeep tick for a wrapper-style launcher.
        members: list[psutil.Process] = []
        seen_leader = False
        #
        # The cheap answer is about a bare PID, so it is asked again once a
        # handle exists, and `is_running()` then confirms the PID still names
        # that handle's process. Asked only in the other order, a PID reused
        # between the two calls got a handle to a process outside the group,
        # which was then signalled (LWSM-1439).
        for pid in psutil.pids():
            try:
                if os.getpgid(pid) != pgid:
                    continue
                if pid == managed.pid:
                    seen_leader = True
                    members.append(managed.handle)
                    continue
                proc = psutil.Process(pid)
                if os.getpgid(pid) == pgid and proc.is_running():
                    members.append(proc)
            except (OSError, psutil.Error):
                continue
        if not seen_leader:
            members.append(managed.handle)
        alive = [proc for proc in members if _alive(proc)]
        if managed.popen is None and not self._vouched(managed, alive, checked_at):
            return []
        return alive

    def _leader_alive(self, managed: ManagedProcess) -> bool:
        """`_alive` on the leader, and for an adopted one, a fresh vouch: while
        it lives, its PID, which is the group id, cannot be reissued."""
        checked_at = _boot_clock()
        alive = _alive(managed.handle)
        if alive and managed.popen is None:
            managed.vouched_at = checked_at
        return alive

    def _vouched(
        self, managed: ManagedProcess, alive: list[psutil.Process], checked_at: float
    ) -> bool:
        """Whether an adopted group is still the one adopted (LWSM-1494).

        An adopted leader is not our child, so nothing holds its PID once the
        whole group has exited, and the kernel may then reissue that id to an
        unrelated group. The id alone cannot tell the two apart. A member that
        started before `vouched_at`, the last moment the group was seen
        occupied, can: it has lived through the whole gap, so the group never
        emptied and every process in it is ours. With none, the group is
        treated as ended. That can disown a server whose every older process
        exited within one tick, leaving only a newer one: the safe direction.

        A live leader vouches by itself, as in `_leader_alive`: its PID is the
        group id. And its start time cannot be compared: psutil caches it on
        this long-lived handle, while `_started_since_boot` takes away a fresh
        boot time, so a backward clock step made the leader read as newer and
        a one-process group was stopped by signalling nothing (LWSM-1513).
        """
        if any(proc is managed.handle for proc in alive):
            managed.vouched_at = checked_at
            return True
        vouched = managed.vouched_at
        if vouched is not None:
            for proc in alive:
                try:
                    started = _started_since_boot(proc)
                except psutil.Error:
                    continue
                if started <= vouched - START_TIME_RESOLUTION_SECONDS:
                    managed.vouched_at = checked_at
                    return True
        return False

    def _wait_for(
        self,
        procs: list[psutil.Process],
        timeout: float,
        _on_wait: Callable[[], None] | None,
    ) -> list[psutil.Process]:
        """`wait_until_gone` on this supervisor's clock, read at each call so
        a test's replacement reaches it."""
        return wait_until_gone(procs, timeout, self._clock, self._sleep, _on_wait)

    def _reap(self, managed: ManagedProcess) -> int | None:
        """Collect the child's exit status, last, and release its log.

        An adopted server has no `Popen` and is reaped by its new parent, so
        there is no status to collect (LWSM-1428 § 4.4).
        """
        if managed.popen is None:
            _close_quietly(managed.log_fd)
            return None
        try:
            exit_code = managed.popen.wait(timeout=KILL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # Handed to a daemon thread rather than abandoned (LWSM-1274): the
            # entry is already popped, so nothing else will ever wait on this
            # child, and a process stuck past SIGKILL still exits eventually.
            # Without the thread it then stays a zombie for the session.
            log.warning(
                "%s did not exit after SIGKILL; reaping it when it does",
                managed.name,
            )
            threading.Thread(
                target=managed.popen.wait, name="lwsm-late-reap", daemon=True
            ).start()
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
        for project, managed in self._entries().items():
            if self._leader_alive(managed):
                continue
            if self._group_members(managed):
                continue
            with self._registry.lock:
                if self._registry.processes.get(project) is not managed:
                    continue
                del self._registry.processes[project]
            self.started.remove(project)
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

    def running(self) -> frozenset[Path]:
        """The projects this manager holds a child for.

        Paths only. The entries hold a live log descriptor and a `Popen`, and a
        caller closing the one or waiting on the other would break the stop
        sequence's ownership of both (known-issue-056, LWSM-1321).
        """
        with self._registry.lock:
            return frozenset(self._registry.processes)

    def _entries(self) -> dict[Path, ManagedProcess]:
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

    def group_alive(self, project: Path) -> bool:
        """Whether anything of our child's process group still runs (LWSM-1389).

        ADR-0004's "own child" is the group: a `start.sh` that forks its
        server and exits has `exited()`, while the server it left is still
        binding. The launcher is asked first because the group walk visits
        every process on the machine, and that cost is paid only once the
        launcher is gone.
        """
        managed = self._get(project)
        if managed is None:
            return False
        return self._leader_alive(managed) or bool(self._group_members(managed))

    def freeze_started_record(self) -> None:
        """Stop writing `started.json`, before a quit lets a relaunch in.

        `main` calls it before releasing the single-instance socket, and
        `close` waits for the queued stops after (LWSM-1447): see
        `StartedStore.freeze`.
        """
        self.started.freeze()

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
            if managed.popen is not None:
                managed.popen.poll()
            _close_quietly(managed.log_fd)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
