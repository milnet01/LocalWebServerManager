"""LWSM-1301 — stopping a server this manager did not start.

ADR-0004 § Consequences is the contract: enumerate the holder's descendants,
name the set, re-enumerate after the user confirms, and signal exactly that set
through `psutil.Process` handles. The fakes below stand in for psutil so every
refusal can be forced; one test runs a real process tree end to end.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import psutil
import pytest

from lwsm import foreign
from lwsm.foreign import (
    Member,
    Tree,
    TreeRefused,
    enumerate_tree,
    looks_like,
    stop_tree,
)


class FakeProcess:
    """A `psutil.Process`-shaped double whose every answer can be forced."""

    def __init__(
        self,
        pid: int,
        started: float = 100.0,
        *,
        children: list[FakeProcess] | None = None,
        exe: str = "/usr/bin/node",
        cmdline: tuple[str, ...] = ("node", "serve.mjs"),
        raise_on: dict[str, Exception] | None = None,
        dies_on: str = "terminate",
        cwd: str = "/home/user",
    ) -> None:
        self.pid = pid
        self._started = started
        self._children = children or []
        self._exe = exe
        self._cmdline = list(cmdline)
        self._raise_on = raise_on or {}
        self._dies_on = dies_on
        self._cwd = cwd
        self.running = True
        self.signals: list[str] = []

    def _check(self, name: str) -> None:
        if name in self._raise_on:
            raise self._raise_on[name]

    def children(self, recursive: bool = False) -> list[FakeProcess]:
        self._check("children")
        found: list[FakeProcess] = []
        for child in self._children:
            found.append(child)
            if recursive:
                found.extend(child.children(recursive=True))
        return found

    def create_time(self) -> float:
        self._check("create_time")
        return self._started

    def exe(self) -> str:
        self._check("exe")
        return self._exe

    def cmdline(self) -> list[str]:
        self._check("cmdline")
        return self._cmdline

    def cwd(self) -> str:
        self._check("cwd")
        return self._cwd

    def terminate(self) -> None:
        self._check("terminate")
        self.signals.append("TERM")
        if self._dies_on == "terminate":
            self.running = False

    def kill(self) -> None:
        self._check("kill")
        self.signals.append("KILL")
        if self._dies_on in ("terminate", "kill"):
            self.running = False

    def is_running(self) -> bool:
        return self.running

    def status(self) -> str:
        return psutil.STATUS_SLEEPING


def lookup(*procs: FakeProcess):
    table = {proc.pid: proc for proc in procs}

    def make(pid: int) -> FakeProcess:
        if pid not in table:
            raise psutil.NoSuchProcess(pid)
        return table[pid]

    return make


class Clock:
    """Advances only when slept on, so a grace period costs no real time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


# --- enumerating the set ------------------------------------------------------


def test_the_set_is_the_holder_then_every_descendant() -> None:
    grandchild = FakeProcess(30)
    child = FakeProcess(20, children=[grandchild])
    holder = FakeProcess(10, children=[child])

    tree = enumerate_tree(10, process=lookup(holder))

    assert [member.pid for member in tree.members] == [10, 20, 30]
    assert tree.members[0] == Member(
        pid=10, started=100.0, exe="/usr/bin/node", cmdline="node serve.mjs"
    )


def test_identity_is_pid_and_start_time_so_a_reused_pid_differs() -> None:
    """The re-enumeration after the dialog compares identities. A PID reused by
    a later process has a different start time and must not compare equal."""
    before = enumerate_tree(10, process=lookup(FakeProcess(10, started=100.0)))
    after = enumerate_tree(10, process=lookup(FakeProcess(10, started=200.0)))

    assert before.identity() != after.identity()
    assert (
        before.identity()
        == enumerate_tree(10, process=lookup(FakeProcess(10, started=100.0))).identity()
    )


def test_a_holder_that_has_gone_is_refused_with_a_reason() -> None:
    with pytest.raises(TreeRefused, match="already stopped"):
        enumerate_tree(10, process=lookup())


def test_a_tree_that_cannot_be_listed_is_refused() -> None:
    holder = FakeProcess(10, raise_on={"children": psutil.AccessDenied(10)})

    with pytest.raises(TreeRefused, match="cannot be inspected"):
        enumerate_tree(10, process=lookup(holder))


def test_a_member_whose_start_time_is_hidden_refuses_the_whole_set() -> None:
    """Without a start time the member cannot be told from a later process
    reusing its PID, so a partial set is not offered."""
    child = FakeProcess(20, raise_on={"create_time": psutil.AccessDenied(20)})
    holder = FakeProcess(10, children=[child])

    with pytest.raises(TreeRefused, match="process 20 cannot be inspected"):
        enumerate_tree(10, process=lookup(holder))


def test_a_member_that_exits_while_listed_is_left_out() -> None:
    child = FakeProcess(20, raise_on={"create_time": psutil.NoSuchProcess(20)})
    holder = FakeProcess(10, children=[child])

    tree = enumerate_tree(10, process=lookup(holder))

    assert [member.pid for member in tree.members] == [10]


def test_hidden_display_fields_are_shown_as_missing_not_refused() -> None:
    holder = FakeProcess(
        10,
        raise_on={
            "exe": psutil.AccessDenied(10),
            "cmdline": psutil.AccessDenied(10),
        },
    )

    member = enumerate_tree(10, process=lookup(holder)).members[0]

    assert (member.exe, member.cmdline) == (None, "")


def test_a_set_containing_this_manager_is_refused(monkeypatch) -> None:
    """The app launched from the terminal that holds the port would otherwise
    offer to stop itself, or the shell it runs under."""
    monkeypatch.setattr(foreign, "_own_lineage", lambda: frozenset({20}))
    holder = FakeProcess(10, children=[FakeProcess(20)])

    with pytest.raises(TreeRefused, match="this manager"):
        enumerate_tree(10, process=lookup(holder))


def test_own_lineage_holds_this_process_and_its_parent() -> None:
    lineage = foreign._own_lineage()

    assert os.getpid() in lineage
    assert os.getppid() in lineage


# --- stopping exactly that set ------------------------------------------------


def _tree(*procs: FakeProcess) -> Tree:
    return Tree(
        members=tuple(Member(pid=p.pid, started=p._started) for p in procs),
        handles=tuple(procs),  # type: ignore[arg-type]
    )


def test_every_member_is_sent_sigterm_and_a_clean_stop_is_ok() -> None:
    procs = (FakeProcess(10), FakeProcess(20))
    clock = Clock()

    outcome = stop_tree(_tree(*procs), clock=clock, sleep=clock.sleep)

    assert outcome.terminated == (10, 20)
    assert outcome.killed == ()
    assert outcome.ok
    assert [p.signals for p in procs] == [["TERM"], ["TERM"]]


def test_a_member_that_ignores_sigterm_is_killed_after_the_grace() -> None:
    stubborn = FakeProcess(20, dies_on="kill")
    clock = Clock()

    outcome = stop_tree(
        _tree(FakeProcess(10), stubborn), grace=1.0, clock=clock, sleep=clock.sleep
    )

    assert outcome.killed == (20,)
    assert stubborn.signals == ["TERM", "KILL"]
    assert clock.now >= 1.0, "the grace period was waited out"
    assert outcome.ok


def test_a_reused_pid_is_skipped_not_killed() -> None:
    """psutil raises NoSuchProcess when the PID now names another process."""
    reused = FakeProcess(20, raise_on={"terminate": psutil.NoSuchProcess(20)})
    reused.running = False
    clock = Clock()

    outcome = stop_tree(_tree(FakeProcess(10), reused), clock=clock, sleep=clock.sleep)

    assert outcome.terminated == (10,)
    assert reused.signals == []
    assert outcome.ok


def test_a_member_the_kernel_will_not_let_us_signal_is_reported() -> None:
    other_user = FakeProcess(
        20,
        raise_on={
            "terminate": psutil.AccessDenied(20),
            "kill": psutil.AccessDenied(20),
        },
        dies_on="never",
    )
    clock = Clock()

    outcome = stop_tree(
        _tree(FakeProcess(10), other_user), grace=0.5, clock=clock, sleep=clock.sleep
    )

    assert outcome.refused == (20,)
    assert outcome.left == (20,)
    assert not outcome.ok


def test_a_member_surviving_sigkill_is_reported_as_left() -> None:
    unkillable = FakeProcess(20, dies_on="never")
    clock = Clock()

    outcome = stop_tree(_tree(unkillable), grace=0.5, clock=clock, sleep=clock.sleep)

    assert outcome.left == (20,)
    assert not outcome.ok


# --- a real tree ----------------------------------------------------------------


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_a_real_tree_is_stopped_and_a_bystander_is_not(tmp_path: Path) -> None:
    """End to end against the kernel: a shell holding two sleeps is the server,
    and a separate sleep in the same directory is the bystander that shares
    nothing with it but a cwd. Run from `tmp_path`, so the suite's orphan check
    (`conftest._no_orphans_outlive_the_run`) catches anything that leaks."""
    server = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 30 & sleep 30 & wait"],
        cwd=tmp_path,
        start_new_session=True,
    )
    bystander = subprocess.Popen(
        ["/bin/sleep", "30"], cwd=tmp_path, start_new_session=True
    )
    try:
        handle = psutil.Process(server.pid)
        assert _wait_for(lambda: len(handle.children()) == 2), "children never started"

        tree = enumerate_tree(server.pid)
        assert len(tree.members) == 3

        outcome = stop_tree(tree, grace=2.0)

        assert outcome.ok, outcome
        assert server.wait(timeout=5) is not None
        assert all(not psutil.pid_exists(m.pid) or _gone(m.pid) for m in tree.members)
        assert bystander.poll() is None, "a process outside the set was signalled"
    finally:
        for proc in (server, bystander):
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)


def _gone(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


# --- "looks like this project" (ADR-0004's display heuristic, LWSM-1011) -------

PROJECT = Path("/srv/site")


@pytest.mark.parametrize(
    ("case", "proc", "expected"),
    [
        ("exe inside", FakeProcess(1, exe="/srv/site/bin/server"), True),
        ("cwd inside", FakeProcess(1, cwd="/srv/site/web"), True),
        (
            "script on the command line",
            FakeProcess(
                1, exe="/usr/bin/python3", cmdline=("python3", "/srv/site/tray.py")
            ),
            True,
        ),
        ("unrelated", FakeProcess(1, exe="/usr/bin/nginx", cwd="/"), False),
        ("sibling sharing a prefix", FakeProcess(1, cwd="/srv/site-old"), False),
        (
            "relative argument",
            FakeProcess(1, exe="/usr/bin/node", cmdline=("node", "serve.mjs")),
            False,
        ),
        (
            "nothing readable",
            FakeProcess(
                1,
                raise_on={
                    "exe": psutil.AccessDenied(1),
                    "cwd": psutil.AccessDenied(1),
                    "cmdline": psutil.AccessDenied(1),
                },
            ),
            False,
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_looks_like_reads_exe_cwd_and_absolute_arguments(case, proc, expected) -> None:
    assert looks_like(1, PROJECT, process=lookup(proc)) is expected, case


def test_looks_like_a_vanished_holder_is_false() -> None:
    assert looks_like(1, PROJECT, process=lookup()) is False
