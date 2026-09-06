"""Service-managed projects — ADR-0003's second column.

A project whose server is a systemd **user** unit is driven with
`systemctl --user`, never by spawning its launcher. ADR-0003 was amended for
exactly this case: systemd already holds an instance, so spawning a second one
would fight it for the port.

Core, no Qt at all, like `ports.py`. Every question that reaches the system goes
through an injected seam, so the tests are the contract rather than a mock of
one (`testing.md § T1`).

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

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lwsm.scanner import valid_unit_name

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

    @property
    def service_managed(self) -> bool:
        """Whether Stop should drive `systemctl` rather than signal a group."""
        return self.unit is not None


@dataclass(frozen=True)
class UnitOutcome:
    """What driving one verb did. Never raises to the caller."""

    ok: bool
    verb: str
    unit: str
    reason: str = ""


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
        leaf = line.strip().rsplit("/", 1)[-1]
        if not leaf.endswith(".service"):
            continue
        if SESSION_UNIT.match(leaf) or not valid_unit_name(leaf):
            return None
        return leaf
    return None


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
