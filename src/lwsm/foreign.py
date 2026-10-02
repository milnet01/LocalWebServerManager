"""Stopping a server this manager did not start — ADR-0004's foreign path.

Core, no Qt at all, like `service.py`. LWSM-1301.

A server started by hand in a terminal is no systemd unit, so `service.py` has
no name to drive it by. ADR-0004 § Consequences sets the rule this module
implements: resolve the holder, enumerate its **descendants**, name the whole
set to the user, **re-enumerate after they confirm**, and signal exactly that
set through `psutil.Process` handles.

**A tree, never a group.** A foreign PID is usually not a group leader: its
group is the terminal job that launched it, which may hold the user's shell.
`os.killpg` would reach processes the user never saw named.

**Handles, never bare PIDs** (ADR-0003). A `psutil.Process` remembers its
`create_time`, and psutil 7.2.2's `_send_signal` raises `NoSuchProcess` when
the PID now names a different process. So a PID recycled between the dialog
and the signal is skipped rather than killed.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import psutil

from lwsm.supervisor import (
    GRACE_SECONDS,
    KILL_TIMEOUT_SECONDS,
    POLL_INTERVAL_SECONDS,
    _alive,
)


class TreeRefused(Exception):
    """The holder's tree cannot be offered for stopping; the message says why."""


@dataclass(frozen=True)
class Member:
    """One process in the tree, as the confirmation dialog shows it.

    `pid` and `started` together are the identity: a PID alone can be reused,
    and the re-enumeration after the dialog compares both.
    """

    pid: int
    started: float
    exe: str | None = None
    cmdline: str = ""


@dataclass(frozen=True)
class Tree:
    """The holder and its descendants, holder first."""

    members: tuple[Member, ...]
    handles: tuple[psutil.Process, ...] = field(compare=False, repr=False)

    def identity(self) -> frozenset[tuple[int, float]]:
        return frozenset((member.pid, member.started) for member in self.members)


@dataclass(frozen=True)
class TreeOutcome:
    """What one stop did. `left` names what was still running at the end."""

    terminated: tuple[int, ...] = ()
    killed: tuple[int, ...] = ()
    refused: tuple[int, ...] = ()
    left: tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.refused and not self.left


def _own_lineage() -> frozenset[int]:
    """This process and its ancestors: never part of a set we signal."""
    pids = {os.getpid()}
    try:
        pids.update(parent.pid for parent in psutil.Process().parents())
    except psutil.Error:
        pass
    return frozenset(pids)


def enumerate_tree(
    holder_pid: int, *, process: Callable[[int], psutil.Process] | None = None
) -> Tree:
    """The holder and every descendant, read now.

    Raises `TreeRefused` rather than returning a partial set: a member whose
    start time cannot be read cannot be told apart from a later process that
    reuses its PID, and the dialog would show a set it cannot vouch for.
    """
    # Resolved here, not as the default: a default binds the function when
    # this module is defined, and a test patching psutil would never reach it.
    make = process if process is not None else psutil.Process
    try:
        holder = make(holder_pid)
        descendants = holder.children(recursive=True)
    except psutil.NoSuchProcess:
        raise TreeRefused("the server has already stopped") from None
    except psutil.Error as exc:
        raise TreeRefused(f"its processes cannot be inspected ({exc})") from None
    own = _own_lineage()
    members: list[Member] = []
    handles: list[psutil.Process] = []
    for proc in (holder, *descendants):
        if proc.pid in own:
            raise TreeRefused("the set includes this manager itself")
        try:
            started = proc.create_time()
        except psutil.NoSuchProcess:
            continue  # exited while we looked: nothing to name or stop
        except psutil.Error as exc:
            raise TreeRefused(
                f"process {proc.pid} cannot be inspected ({exc})"
            ) from None
        members.append(
            Member(
                pid=proc.pid,
                started=started,
                exe=_ask(proc.exe),
                cmdline=" ".join(_ask(proc.cmdline) or ()),
            )
        )
        handles.append(proc)
    if not members:
        raise TreeRefused("the server has already stopped")
    return Tree(members=tuple(members), handles=tuple(handles))


def _ask[T](question: Callable[[], T]) -> T | None:
    """A field the disclosure shows but identity does not need: None if hidden."""
    try:
        return question()
    except psutil.Error:
        return None


def stop_tree(
    tree: Tree,
    *,
    grace: float = GRACE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TreeOutcome:
    """SIGTERM the set, wait `grace`, SIGKILL what is left of it.

    Exactly the confirmed set: nothing is re-enumerated here, because a process
    that joined the tree since the dialog is one the user never saw named.
    One that survives is reported in `left`, not chased.
    """
    terminated: list[int] = []
    refused: list[int] = []
    for proc in tree.handles:
        try:
            proc.terminate()
            terminated.append(proc.pid)
        except psutil.NoSuchProcess:
            pass  # exited, or its PID now names someone else: either way, skip
        except psutil.Error:
            refused.append(proc.pid)
    survivors = _wait(list(tree.handles), grace, clock, sleep)
    killed: list[int] = []
    for proc in survivors:
        try:
            proc.kill()
            killed.append(proc.pid)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error:
            if proc.pid not in refused:
                refused.append(proc.pid)
    left = _wait(survivors, KILL_TIMEOUT_SECONDS, clock, sleep) if killed else survivors
    return TreeOutcome(
        terminated=tuple(terminated),
        killed=tuple(killed),
        refused=tuple(refused),
        left=tuple(proc.pid for proc in left),
    )


def _wait(
    procs: list[psutil.Process],
    timeout: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> list[psutil.Process]:
    """Poll until nothing in `procs` is alive or `timeout` passes."""
    deadline = clock() + timeout
    while True:
        alive = [proc for proc in procs if _alive(proc)]
        if not alive or clock() >= deadline:
            return alive
        sleep(POLL_INTERVAL_SECONDS)
