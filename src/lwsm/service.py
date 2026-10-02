"""Service-managed projects — ADR-0003's second column.

A project whose server is a systemd **user** unit is driven with
`systemctl --user`, never by spawning its launcher. ADR-0003 was amended for
exactly this case: systemd already holds an instance, so spawning a second one
would fight it for the port.

Core, no Qt at all, like `ports.py`. Every question that reaches the system goes
through an injected seam, so the tests are the contract rather than a mock of
one (`testing-overrides.md § T1`).

**Nothing here signals a process, and that is the point.** ADR-0003 forbids
signalling a bare PID; a unit name is what makes it unnecessary. `systemctl`
resolves the name itself, inside the caller's own session, so a PID recycled
between the probe and the stop cannot be signalled by mistake — the hazard
`Supervisor._raise_if_pid_reused` exists to catch on the managed path.

**Stopping a unit does not disable it.** `stop` and `disable` are separate
systemd verbs, so a server stopped from here still starts at the next logon.
That is the behaviour asked for (user decision, 2026-09-06), and it costs
nothing: `disable` simply never appears in `VERBS`.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lwsm.configfile import ConfigFileError, write_atomically
from lwsm.scanner import (
    SystemctlUnits,
    _exec_start_argv,
    bound_inside,
    valid_unit_name,
)

# The only verbs this module will drive. `disable` and `mask` are absent
# deliberately, not by oversight: the user asked to manage servers WITHOUT
# losing their start at logon, and a module that cannot express `disable`
# cannot regress that in a later edit.
VERBS = ("start", "stop", "restart")

# A stop can legitimately take a while — systemd sends SIGTERM and waits out the
# unit's own TimeoutStopSec. This bounds how long the app waits before SAYING it
# does not know, and a timeout is reported rather than retried: re-issuing a
# stop that is already in progress achieves nothing.
UNIT_VERB_TIMEOUT_SECONDS = 15.0

# A process sitting directly under the session manager names no server. Driving
# `user@1000.service` would "stop" the port by tearing down the whole user
# session and logging the user out, and `init.scope` is the same shape. There is
# no legitimate server these could name, so they are refused before any argv is
# built rather than trusted to be unreachable.
SESSION_UNIT = re.compile(r"^(user@\d+\.service|init\.scope)$")


@dataclass(frozen=True)
class Holder:
    """Who holds a port: ADR-0004's four disclosure fields, plus the unit.

    ADR-0004 requires that acting on a server this app did not start first shows
    "the holder's executable path, uid, cmdline and start time". Those four are
    the fields; `unit` is the fifth because it is the one that turns a guess
    into an identity, and the one the Stop path drives.

    Every field except `pid` is optional. A process can exit between the socket
    read and this call, and a holder owned by another user answers nothing at
    all without privileges — so a missing field is reported as missing rather
    than filled with a plausible default, which is what the disclosure is for.
    """

    pid: int
    exe: str | None = None
    uid: int | None = None
    cmdline: str = ""
    started: float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class UnitOutcome:
    """What driving one verb did. Never raises to the caller."""

    ok: bool
    verb: str
    unit: str
    reason: str = ""
    # Refused because the unit is not this project's (ADR-0003's binding rule),
    # so the caller forgets it rather than offering it again.
    unbound: bool = False


# A unit under a user's own service manager, the only kind `--user` drives.
_USER_MANAGER = re.compile(r"/user@\d+\.service/")


def _read_cgroup(pid: int) -> str:
    return Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8", errors="replace")


def unit_for_pid(pid: int, *, read_cgroup: object = None) -> str | None:
    """The systemd user unit a process belongs to, or None.

    Read from the process's own cgroup, which is the kernel's answer rather than
    a match. That matters here: `ProjectRecord.unit` is empty for every project
    on the reporting machine, so a registry lookup would have adopted nothing at
    all, while the cgroup names the unit for both servers exactly.

    The **escaped** name is returned on purpose —
    `app-ai\\x2dprompts\\x2dtray@autostart.service` — because that is the only
    form `systemctl` accepts. `scanner._unescape_unit_name` exists for display
    and comparison, never for driving.

    Answers None rather than raising for every failure, including a process that
    has already exited. A holder we cannot name is simply not service-managed,
    which sends the caller down the signalling path with its own disclosure.
    """
    reader = read_cgroup if read_cgroup is not None else _read_cgroup
    try:
        raw = reader(pid)  # type: ignore[operator]
    except (OSError, ValueError):
        return None
    if not isinstance(raw, str):
        return None
    # Last path segment of the deepest line: cgroup v2 writes one `0::/...`
    # line, v1 writes several, and in both the unit is the leaf of the path.
    for line in reversed([entry for entry in raw.splitlines() if entry.strip()]):
        if not _USER_MANAGER.search(line):
            # A system service is not one `systemctl --user` can drive, and a
            # user unit of the same name is a DIFFERENT unit (review-code
            # 2026-10-01 L3-L5).
            continue
        leaf = line.strip().rsplit("/", 1)[-1]
        if not leaf.endswith(".service"):
            continue
        if SESSION_UNIT.match(leaf) or not valid_unit_name(leaf):
            return None
        return leaf
    return None


# What `unit_belongs_to` reads. `ExecStart` is the anchor an XDG-autostart unit
# actually carries: its `FragmentPath` is generated under /run/user and its
# `WorkingDirectory` is often the home directory (measured 2026-10-02).
ADOPTION_PROPERTIES = ("FragmentPath", "WorkingDirectory", "ExecStart")
ADOPTION_TIMEOUT_SECONDS = 5.0


def unit_belongs_to(
    unit: str, project: Path, *, properties: object = None
) -> bool | None:
    """Whether a unit found holding a project's port is that project's own.

    `unit_for_pid` names the unit the holder runs in, which is not the same
    thing: a server started from a terminal inside an autostarted IDE runs in
    the IDE's unit, and driving that stops the IDE (review-code 2026-10-01
    L3-M4). ADR-0003 binds a unit to a row only when it points inside the
    project — its unit file, its working directory, or an absolute path in its
    command line.

    None means the properties could not be read, which proves nothing either
    way; the caller refuses rather than guessing.
    """
    reader = properties if properties is not None else SystemctlUnits().properties
    try:
        props = reader(unit, ADOPTION_PROPERTIES, ADOPTION_TIMEOUT_SECONDS)  # type: ignore[operator]
    except (OSError, ValueError):
        return None
    try:
        candidate = project.resolve()
    except (OSError, ValueError):
        return None
    if any(
        bound_inside(props.get(field, ""), candidate)
        for field in ("FragmentPath", "WorkingDirectory")
    ):
        return True
    argv = _exec_start_argv(props.get("ExecStart", "")) or ""
    # `bound_inside` refuses a relative token, so the interpreter's own
    # arguments (`-u`, `serve.mjs`) contribute nothing — only absolute paths
    # can anchor, which is the evidence a spoofed cwd cannot supply. And only a
    # FILE: an autostarted editor handed the project's directory names a path
    # inside it without being its server. Checked after `bound_inside`, so a
    # relative token is never resolved against our own cwd.
    return any(
        bound_inside(token, candidate) and Path(token).is_file()
        for token in (raw.strip("'\"") for raw in argv.split())
    )


def describe_holder(
    pid: int, *, process: object = None, read_cgroup: object = None
) -> Holder:
    """The disclosure ADR-0004 requires, gathered from one process.

    `process` is the `psutil.Process`-shaped seam. Imported inside the function
    so a test can drive the whole module without psutil resolving a real PID,
    and so this module keeps its no-side-effect import.

    Each field is read in its own `try`: a holder owned by another user answers
    some questions and refuses others, and losing the whole disclosure to one
    `AccessDenied` would leave the dialog emptier than the facts warrant.
    """
    handle = process
    if handle is None:
        import psutil

        try:
            handle = psutil.Process(pid)
        except Exception:
            return Holder(pid=pid, unit=unit_for_pid(pid, read_cgroup=read_cgroup))

    def ask(name: str, convert: object) -> object:
        try:
            return convert(getattr(handle, name)())  # type: ignore[operator]
        except Exception:
            return None

    uids = ask("uids", lambda value: getattr(value, "real", None))
    return Holder(
        pid=pid,
        exe=ask("exe", str),  # type: ignore[arg-type]
        uid=uids,  # type: ignore[arg-type]
        cmdline=ask("cmdline", lambda value: " ".join(value)) or "",  # type: ignore[arg-type]
        started=ask("create_time", float),  # type: ignore[arg-type]
        unit=unit_for_pid(pid, read_cgroup=read_cgroup),
    )


def unit_argv(verb: str, unit: str) -> list[str]:
    """The argv for one verb, built in the order ADR-0003 requires.

    `--` before the unit name, so a name that begins with a dash cannot be read
    as an option — the same separator rule `scanner._show_argv` records, and it
    is built here rather than inline so a caller cannot ship one without it.
    """
    if verb not in VERBS:
        raise ValueError(f"refusing to drive {verb!r}: not one of {VERBS}")
    if not valid_unit_name(unit) or SESSION_UNIT.match(unit):
        raise ValueError(f"refusing to drive {unit!r}: not a drivable unit name")
    return ["systemctl", "--user", verb, "--", unit]


def drive_unit(verb: str, unit: str, *, run: object = None) -> UnitOutcome:
    """Run one `systemctl --user` verb against one unit.

    Reports rather than raises, because the caller is a button: every failure
    mode here is something the user needs told, not an exception to propagate
    through a Qt slot, where PySide6 would swallow it (`CLAUDE.md`).

    An exit status of 0 means systemd accepted the verb, and nothing more. The
    port is re-probed on the next poll and that is what decides the row's state
    — the same rule ADR-0004 already applies to a managed stop.
    """
    try:
        argv = unit_argv(verb, unit)
    except ValueError as exc:
        return UnitOutcome(ok=False, verb=verb, unit=unit, reason=str(exc))

    runner = run if run is not None else subprocess.run
    try:
        completed = runner(  # type: ignore[operator]
            argv,
            capture_output=True,
            text=True,
            # "Never raises": strict decoding makes undecodable stderr a
            # `UnicodeDecodeError`, which is a `ValueError` (L3-L4).
            errors="replace",
            timeout=UNIT_VERB_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return UnitOutcome(
            ok=False, verb=verb, unit=unit, reason="systemctl is not installed"
        )
    except subprocess.TimeoutExpired:
        return UnitOutcome(
            ok=False,
            verb=verb,
            unit=unit,
            reason=f"systemctl {verb} did not finish within "
            f"{UNIT_VERB_TIMEOUT_SECONDS:.0f} seconds",
        )
    except OSError as exc:
        return UnitOutcome(ok=False, verb=verb, unit=unit, reason=str(exc))

    if getattr(completed, "returncode", 1) == 0:
        return UnitOutcome(ok=True, verb=verb, unit=unit)
    # systemd's own message, trimmed. `configfile.MAX_REASON_CHARS` exists for
    # exactly this shape of foreign text reaching a widget; the bound is applied
    # here so no caller can forget it.
    from lwsm.configfile import MAX_REASON_CHARS

    detail = (getattr(completed, "stderr", "") or "").strip().replace("\n", " ")
    return UnitOutcome(
        ok=False,
        verb=verb,
        unit=unit,
        reason=detail[:MAX_REASON_CHARS] or f"systemctl {verb} failed",
    )


# --------------------------------------------------------------------------
# The drop-in (ADR-0003 § Service-managed projects, LWSM-1028)
# --------------------------------------------------------------------------

# Owned and namespaced, so this app removes exactly its own override and never a
# drop-in somebody else wrote.
DROP_IN_NAME = "50-lwsm-port.conf"


def user_unit_dir() -> Path:
    """`$XDG_CONFIG_HOME/systemd/user`, where systemd reads user drop-ins.

    `~/.config` when the variable is unset or not absolute, which is the rule
    systemd itself applies.
    """
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(raw) if raw and Path(raw).is_absolute() else Path.home() / ".config"
    return base / "systemd" / "user"


def drop_in_path(unit: str) -> Path:
    """Where this app's drop-in for `unit` lives. The name is validated first:
    it becomes a directory name, and `valid_unit_name` admits no `/`."""
    if not valid_unit_name(unit) or SESSION_UNIT.match(unit):
        raise ValueError(f"refusing {unit!r}: not a drivable unit name")
    return user_unit_dir() / f"{unit}.d" / DROP_IN_NAME


def drop_in_text(port: int | None) -> str:
    """The drop-in's body: the two variables `design.md § Data flow` step 2
    says travel here, because systemd starts a unit in its own environment and
    never the caller's. No `PORT` line when the app knows no port."""
    lines = ["[Service]"]
    if port is not None:
        lines.append(f"Environment=PORT={port}")
    lines.append("Environment=LWSM_MANAGED=1")
    return "\n".join(lines) + "\n"


def reload_user_manager(*, run: object = None) -> UnitOutcome:
    """`systemctl --user daemon-reload`, so a drop-in change takes effect.

    Not in `VERBS`: it names no unit and changes no unit's state. The tests
    replace this module attribute wholesale (`conftest.py`), so no test run
    reloads the real user manager.
    """
    runner = run if run is not None else subprocess.run
    verb = "daemon-reload"
    try:
        completed = runner(  # type: ignore[operator]
            ["systemctl", "--user", verb],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=UNIT_VERB_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return UnitOutcome(
            ok=False, verb=verb, unit="", reason="systemctl is not installed"
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return UnitOutcome(ok=False, verb=verb, unit="", reason=str(exc))
    if getattr(completed, "returncode", 1) == 0:
        return UnitOutcome(ok=True, verb=verb, unit="")
    from lwsm.configfile import MAX_REASON_CHARS

    detail = (getattr(completed, "stderr", "") or "").strip().replace("\n", " ")
    return UnitOutcome(
        ok=False,
        verb=verb,
        unit="",
        reason=detail[:MAX_REASON_CHARS] or "systemctl daemon-reload failed",
    )


def set_drop_in(unit: str, port: int | None) -> UnitOutcome:
    """Write this app's drop-in for `unit`, then reload — before a start.

    Unchanged bytes skip both the write and the reload, so a second Start does
    not reload the user's whole service manager for nothing. A failure is
    reported and the caller does not start: a unit started without its drop-in
    runs on its own default port, which is ADR-0002's silent no-op.
    """
    try:
        path = drop_in_path(unit)
    except ValueError as exc:
        return UnitOutcome(ok=False, verb="start", unit=unit, reason=str(exc))
    data = drop_in_text(port).encode("utf-8")
    try:
        if path.read_bytes() == data:
            return UnitOutcome(ok=True, verb="daemon-reload", unit=unit)
    except OSError:
        pass  # absent, or unreadable: write it
    try:
        write_atomically(path, data, prefix=".lwsm-")
    except ConfigFileError as exc:
        return UnitOutcome(ok=False, verb="start", unit=unit, reason=str(exc))
    return reload_user_manager()


def clear_drop_in(unit: str) -> UnitOutcome:
    """Remove this app's drop-in for `unit`, then reload — after a stop.

    Removing rather than rewriting returns the unit to exactly its packaged
    default (ADR-0003), so its next start at logon is its own. Nothing to
    remove is success with no reload. Only our own file is touched; the
    `<unit>.d` directory stays, since it may hold someone else's drop-ins.
    """
    try:
        path = drop_in_path(unit)
    except ValueError as exc:
        return UnitOutcome(ok=False, verb="stop", unit=unit, reason=str(exc))
    try:
        path.unlink()
    except FileNotFoundError:
        return UnitOutcome(ok=True, verb="daemon-reload", unit=unit)
    except OSError as exc:
        return UnitOutcome(
            ok=False,
            verb="stop",
            unit=unit,
            reason=f"could not remove {DROP_IN_NAME} ({exc.strerror or exc})",
        )
    return reload_user_manager()


# The `ActiveState` values that end a start: the unit is not running and is not
# about to be. `activating` and `reloading` are still on their way, and a slow
# start is not a failure (ADR-0004 § Slowness is not failure).
ENDED_STATES = frozenset({"failed", "inactive"})


def unit_state(unit: str, *, run: object = None) -> str | None:
    """A unit's `ActiveState` from `systemctl --user is-active`, or `None`.

    The service-side counterpart of `Supervisor.exited()` (L6-M3): a verb's
    exit code says only that systemd accepted it, so a unit that crashes right
    after `start` is visible here and nowhere else. A query, not a verb, so it
    is not in `VERBS` and cannot change anything.

    `None` means unreadable, which is not evidence of anything. `is-active`
    exits non-zero for every state but `active`, so stdout is read regardless.
    """
    if not valid_unit_name(unit) or SESSION_UNIT.match(unit):
        return None
    runner = run if run is not None else subprocess.run
    try:
        completed = runner(  # type: ignore[operator]
            ["systemctl", "--user", "is-active", "--", unit],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=UNIT_VERB_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (getattr(completed, "stdout", "") or "").strip() or None
