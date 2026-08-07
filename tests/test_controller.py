"""LWSM-1005 INV-3, INV-4, INV-4b, INV-5, INV-11, INV-12, INV-16.

The controller's whole job is to derive status from observation and say so
once. Every test here injects a fake probe, which the `SupportsSnapshot`
Protocol makes the declared contract rather than a duck-typing accident.

Marked `gui`: a QTimer, QThreadPool and queued cross-thread signals all need a
Qt application object, which `qtbot` supplies (`docs/standards/testing.md
§ T6`).
"""

from __future__ import annotations

import gc
import logging
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from lwsm import controller as controller_module
from lwsm.controller import ProjectController, ProjectStatus
from lwsm.ports import PortSnapshot, ProbeError
from lwsm.registry import ProjectRecord

pytestmark = pytest.mark.gui


class FakeProbe:
    """Records what it was asked, and on which thread."""

    def __init__(self, *ports: int) -> None:
        self.listening = set(ports)
        self.calls = 0
        self.threads: list[int] = []
        self.gate: threading.Event | None = None
        # Set on the pool thread as the probe returns. Waiting on this rather
        # than on `qtbot.waitUntil` is the point: waitUntil spins the event
        # loop, which would deliver the very emission a test may need to still
        # be in flight when it calls stop().
        self.finished = threading.Event()

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        self.threads.append(threading.get_ident())
        if self.gate is not None:
            self.gate.wait(timeout=5)
        try:
            return PortSnapshot(frozenset(self.listening))
        finally:
            self.finished.set()


class FailingProbe:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        raise ProbeError("socket table unavailable")


class ExplodingProbe:
    """Raises something the poll loop was never told to expect (LWSM-1069).

    Not a ProbeError: the failure this exists to catch is an exception the
    task's `except` clause does not name, which PySide6 swallows on the way out
    of `QRunnable.run()`.
    """

    def __init__(self, exc: BaseException | None = None) -> None:
        self.calls = 0
        self._exc = exc or RuntimeError("malformed /proc/net/tcp line")

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        raise self._exc


def record(name: str, port: int | None = 5005) -> ProjectRecord:
    return ProjectRecord(
        path=Path(f"/srv/{name}"), name=name, port=port, port_override=None
    )


@pytest.fixture
def controllers() -> Iterator[list[ProjectController]]:
    """Every controller built here is stopped in teardown (§ T5, INV-16)."""
    built: list[ProjectController] = []
    yield built
    for controller in built:
        controller.stop()


def build(controllers: list[ProjectController], records, probe) -> ProjectController:
    controller = ProjectController(records, probe)
    controllers.append(controller)
    return controller


# --- INV-3: one snapshot per poll, whatever the record count -------------------


def test_one_snapshot_per_poll(qtbot, controllers) -> None:
    probe = FakeProbe()
    records = [record(f"p{i}", 5000 + i) for i in range(10)]
    controller = build(controllers, records, probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert probe.calls == 1, "ten records, one socket-table read"


# --- INV-4 / INV-4b: derived, not remembered ----------------------------------


def test_status_is_rederived_not_remembered(qtbot, controllers) -> None:
    # Two ticks on ONE controller. A fresh controller is not a valid fixture:
    # having no previous status it reports RUNNING under a sticky
    # implementation too, so it cannot fail for the breach INV-4 names.
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.STOPPED


def test_probe_error_holds_previous_status(qtbot, controllers) -> None:
    class FlakyProbe:
        def __init__(self) -> None:
            self.fail = False

        def snapshot(self) -> PortSnapshot:
            if self.fail:
                raise ProbeError("gone")
            return PortSnapshot(frozenset({5005}))

    probe = FlakyProbe()
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING

    probe.fail = True
    with qtbot.assertNotEmitted(controller.projects_changed, wait=300):
        controller.poll_once()
    # Reporting `stopped` on a failed probe would report a state nobody
    # observed, and it would look like news.
    assert controller.rows()[0].status is ProjectStatus.RUNNING


def test_a_failing_first_poll_still_emits(qtbot, controllers) -> None:
    # Exempt from INV-4b: with nothing before it, suppressing the emission
    # would leave the window at its blank initial state forever.
    controller = build(controllers, [record("a")], FailingProbe())

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.UNKNOWN


def test_no_port_is_unknown_not_stopped(qtbot, controllers) -> None:
    controller = build(controllers, [record("a", port=None)], FakeProbe())

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows()[0].status is ProjectStatus.UNKNOWN


# --- INV-5: first poll always emits; afterwards only on change ----------------


def test_first_poll_emits_then_only_on_change(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    # Same statuses: a screen reader must not re-announce every row.
    with qtbot.assertNotEmitted(controller.projects_changed, wait=300):
        controller.poll_once()

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()


def test_first_poll_emits_with_zero_records(qtbot, controllers) -> None:
    # The case a difference-based emitter fails: the status map is empty before
    # and after, so nothing "differs" and the empty window is never rendered.
    controller = build(controllers, [], FakeProbe())

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows() == []


# --- INV-11 / INV-12 / INV-16: the worker ------------------------------------


def test_probe_runs_off_the_owning_thread(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)
    owning_thread = threading.get_ident()

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert probe.threads, "the probe was never called"
    assert owning_thread not in probe.threads, (
        "psutil must not block the thread that owns the window"
    )


def test_tick_skipped_while_probe_in_flight(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    probe.gate = threading.Event()
    controller = build(controllers, [record("a")], probe)

    controller.poll_once()
    controller.poll_once()  # must be dropped, not queued

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        probe.gate.set()

    # Asserted only after the outstanding task completed (§ T4) — taken any
    # earlier it would count one call and pass for the wrong reason.
    assert probe.calls == 1


def test_stop_waits_for_the_outstanding_task(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    probe.gate = threading.Event()
    controller = build(controllers, [record("a")], probe)

    controller.poll_once()
    probe.gate.set()
    controller.stop()

    # After stop() returns nothing is outstanding, so a snapshot arriving later
    # cannot touch a torn-down controller.
    assert probe.calls == 1


# --- LWSM-1069: an unexpected exception must not wedge the loop ---------------


def test_an_unexpected_exception_does_not_wedge_the_poll_loop(
    qtbot, controllers
) -> None:
    """The failure the worker exists to prevent, inverted.

    An exception escaping `QRunnable.run()` is swallowed by PySide6 — the
    process survives at exit 0 and **no** signal is emitted, so the in-flight
    guard is never cleared and every later tick returns early for the life of
    the process. The window then shows plausible, permanently frozen data.
    """
    probe = ExplodingProbe()
    controller = build(controllers, [record("a")], probe)

    # The first poll emits either way (INV-5). Under the swallowed exception it
    # emits nothing at all, so this waits out its timeout.
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert probe.calls == 1

    # The tick after the failure is the whole test: wedged, it stays at 1.
    controller.poll_once()
    qtbot.waitUntil(lambda: probe.calls == 2, timeout=2000)


def test_the_loop_recovers_once_the_probe_does(qtbot, controllers) -> None:
    """A wedge is invisible; a recovery proves the guard was really cleared."""

    class RecoveringProbe:
        def __init__(self) -> None:
            self.explode = True

        def snapshot(self) -> PortSnapshot:
            if self.explode:
                raise RuntimeError("malformed /proc/net/tcp line")
            return PortSnapshot(frozenset({5005}))

    probe = RecoveringProbe()
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.UNKNOWN

    probe.explode = False
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING


def test_an_unexpected_exception_is_reported_not_silent(
    qtbot, controllers, caplog
) -> None:
    """Frozen data with no dialog, no status change and no log line is the
    least debuggable failure this app can have."""
    controller = build(controllers, [record("a")], ExplodingProbe())

    with caplog.at_level(logging.DEBUG, logger="lwsm.controller"):
        with qtbot.waitSignal(controller.projects_changed, timeout=2000):
            controller.poll_once()

    assert "RuntimeError" in caplog.text, (
        "the app log must name what actually went wrong, not just that it did"
    )
    # The assertion above cannot tell "traceback reported" from "no traceback":
    # the wrapping ProbeError's own message carries the string "RuntimeError"
    # from a different log line, so replacing `log.exception` in `run()` with
    # `pass` left it green (LWSM-1109). Only `log.exception` attaches exc_info.
    with_traceback = [record for record in caplog.records if record.exc_info]
    assert with_traceback, (
        "no log record carries a traceback — an unexpected exception is a "
        "defect report, and the stack is the report"
    )


def test_a_held_status_survives_an_unexpected_exception(qtbot, controllers) -> None:
    """INV-4b holds for any failed probe, not only a ProbeError: an unreadable
    socket table is not evidence that anything stopped."""

    class FlakyProbe:
        def __init__(self) -> None:
            self.explode = False

        def snapshot(self) -> PortSnapshot:
            if self.explode:
                raise RuntimeError("malformed /proc/net/tcp line")
            return PortSnapshot(frozenset({5005}))

    probe = FlakyProbe()
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING

    probe.explode = True
    with qtbot.assertNotEmitted(controller.projects_changed, wait=300):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING


# --- LWSM-1079: a permanent failure must not scrub the log --------------------


def drain(qtbot, controller, probe, ticks: int) -> None:
    """Run `ticks` complete polls, waiting for each to land."""
    for expected in range(1, ticks + 1):
        controller.poll_once()
        # Bound `expected` at definition time: a bare closure over the loop
        # variable would read its final value on every iteration.
        qtbot.waitUntil(lambda n=expected: probe.calls >= n, timeout=2000)
        qtbot.wait(10)


def test_a_repeated_probe_failure_is_logged_once(qtbot, controllers, caplog) -> None:
    """The poll is 1000 ms, so a permanently unreadable socket table wrote
    roughly 86,400 lines a day into a handler that rotates at 1 MiB keeping 5 —
    discarding the history the user is told to consult."""
    probe = FailingProbe()
    controller = build(controllers, [record("a")], probe)

    with caplog.at_level(logging.WARNING, logger="lwsm.controller"):
        drain(qtbot, controller, probe, 5)

    assert probe.calls == 5, "the loop must keep polling"
    lines = [r for r in caplog.records if "socket table unavailable" in r.getMessage()]
    assert len(lines) == 1, f"{len(lines)} log lines for one unchanging failure"


def test_a_changed_failure_message_is_logged_again(qtbot, controllers, caplog) -> None:
    """Suppressing by *message* rather than by count: a different failure is
    news, and hiding it would be the over-correction."""

    class DriftingProbe:
        def __init__(self) -> None:
            self.calls = 0

        def snapshot(self) -> PortSnapshot:
            self.calls += 1
            raise ProbeError(f"failure number {self.calls}")

    probe = DriftingProbe()
    controller = build(controllers, [record("a")], probe)

    with caplog.at_level(logging.WARNING, logger="lwsm.controller"):
        drain(qtbot, controller, probe, 3)

    logged = [
        r.getMessage() for r in caplog.records if "failure number" in r.getMessage()
    ]
    assert len(logged) == 3, logged


def test_the_suppressed_repeats_are_counted(qtbot, controllers, caplog) -> None:
    """Silence and suppression must be distinguishable in the log."""
    probe = FailingProbe()
    controller = build(controllers, [record("a")], probe)

    with caplog.at_level(logging.WARNING, logger="lwsm.controller"):
        drain(qtbot, controller, probe, 4)
        controller.stop()

    assert any("repeated 3" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


# --- LWSM-1073: stop() must actually stop, promptly, and only itself ----------


def test_no_snapshot_is_delivered_after_stop(qtbot, controllers) -> None:
    """INV-16 passed on its wording while failing its stated purpose.

    `waitForDone` waits for `run()` to *finish*, but the emit happens inside
    `run()` over a queued connection — so the event is already posted and is
    dispatched on the next event-loop spin, into a controller the app has
    already torn down. `mainwindow.py` connects that signal, so the late
    delivery re-enters the window's widgets after teardown.

    The probe is allowed to **complete** before `stop()` is called, which is
    the window a disconnect cannot close: Qt dispatches a `QMetaCallEvent`
    that has already been posted regardless of any later disconnect
    (LWSM-1098). Gating the probe instead puts the emit *inside*
    `waitForDone`, after the disconnect, where the earlier shape of this test
    could only catch "no disconnect at all".
    """
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)
    emissions: list[int] = []
    controller.projects_changed.connect(lambda: emissions.append(1))

    controller.poll_once()
    assert probe.finished.wait(timeout=5), "the probe never ran"
    # The emit is the next statement after the probe returns; this lets it be
    # posted without spinning the loop that would deliver it.
    time.sleep(0.05)

    controller.stop()
    assert emissions == [], "nothing is dispatched before the loop spins"

    # One spin is all it took to reproduce the late delivery.
    qtbot.wait(200)
    assert emissions == [], "a snapshot arrived after stop() returned"


def test_a_poll_started_after_stop_delivers_nothing(qtbot, controllers) -> None:
    """`poll_once` was unguarded, so a stray tick re-armed delivery into a
    controller that had already been torn down (LWSM-1111)."""
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)
    emissions: list[int] = []
    controller.projects_changed.connect(lambda: emissions.append(1))

    controller.stop()
    controller.poll_once()
    qtbot.wait(200)

    assert probe.calls == 0, "a stopped controller must not probe again"
    assert emissions == [], "a stopped controller emitted"


def test_completed_tasks_do_not_accumulate(qtbot, controllers) -> None:
    """`setAutoDelete(False)` kept every task for the life of the process.

    `QThreadPool.start()` transfers ownership to C++, so the slot clearing the
    controller's own reference freed nothing: one `_SnapshotTask` and one
    `_SnapshotSignals` per tick, about **210 MiB/day** at the 1000 ms
    interval, in an app whose whole point is to stay open (LWSM-1099). Each
    leaked signaller also held two live connections into the controller, so
    the connection list grew without bound beside it.

    The probe toggles so every poll changes status and therefore emits
    (INV-5), which is what makes each iteration wait for a *completed* poll
    rather than for a sleep.
    """

    class TogglingProbe:
        def __init__(self) -> None:
            self.calls = 0

        def snapshot(self) -> PortSnapshot:
            self.calls += 1
            return PortSnapshot(frozenset({5005} if self.calls % 2 else set()))

    probe = TogglingProbe()
    controller = build(controllers, [record("a")], probe)

    def live(kind: type) -> int:
        gc.collect()
        return sum(1 for obj in gc.get_objects() if type(obj) is kind)

    polls = 200
    for _ in range(polls):
        with qtbot.waitSignal(controller.projects_changed, timeout=2000):
            controller.poll_once()
    assert probe.calls == polls

    # At most the one still referenced by the controller — never one per tick.
    tasks = live(controller_module._SnapshotTask)
    signals = live(controller_module._SnapshotSignals)
    assert tasks <= 1, f"{tasks} live tasks after {polls} completed polls"
    assert signals <= 1, f"{signals} live signallers after {polls} completed polls"


def test_stop_does_not_wait_on_unrelated_work(qtbot, controllers) -> None:
    """The controller waited on `QThreadPool.globalInstance()`, so its shutdown
    blocked on every unrelated runnable in the process — including the
    per-project reader threads `design.md § State management` already plans."""
    from PySide6.QtCore import QRunnable, QThreadPool

    release = threading.Event()

    class Blocker(QRunnable):
        def run(self) -> None:
            release.wait(timeout=5)

    QThreadPool.globalInstance().start(Blocker())
    try:
        probe = FakeProbe(5005)
        controller = build(controllers, [record("a")], probe)
        controller.poll_once()

        started = time.perf_counter()
        controller.stop()
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0, (
            f"stop() took {elapsed:.2f}s — it is waiting on the global pool, "
            f"not on its own probe"
        )
    finally:
        release.set()
        QThreadPool.globalInstance().waitForDone()


@pytest.mark.integration
def test_the_process_exits_promptly_when_a_probe_is_abandoned(tmp_path) -> None:
    """`stop()` being bounded is not the same as the process being bounded.

    `stop()` moved a still-running pool into `_ABANDONED` on the stated
    premise that holding it means it is "deliberately never released". CPython
    releases module globals at interpreter shutdown, which runs
    `~QThreadPool`, which calls `waitForDone()` with **no timeout** — so the
    budget did not remove the unbounded wait, it moved it thirty lines later.
    Measured before the fix: `stop()` returned in 0.10 s and the process took
    4.16 s to exit behind a 4 s probe (LWSM-1100).

    Measures the **process**, in a subprocess, because that is the thing whose
    boundedness `§ 6` is about; every in-process assertion here passed while
    the defect was live.
    """
    script = tmp_path / "abandon_a_probe.py"
    script.write_text(
        textwrap.dedent(
            """
            import os, sys, time
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from pathlib import Path
            from PySide6.QtCore import QCoreApplication
            from lwsm import controller as cm
            from lwsm.controller import ProjectController
            from lwsm.ports import PortSnapshot
            from lwsm.registry import ProjectRecord

            cm.STOP_WAIT_MS = 100

            class HangingProbe:
                def snapshot(self):
                    time.sleep(30)
                    return PortSnapshot(frozenset())

            app = QCoreApplication([])
            record = ProjectRecord(
                path=Path("/srv/a"), name="a", port=5005, port_override=None
            )
            controller = ProjectController([record], HangingProbe())
            controller.poll_once()
            time.sleep(0.3)          # let the probe reach its sleep
            controller.stop()        # bounded at 100 ms, abandons the pool
            cm.exit_without_waiting_for_abandoned_probes(0)
            sys.exit(0)              # only reached when nothing was abandoned
            """
        )
    )

    started = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90
    )
    elapsed = time.perf_counter() - started

    assert proc.returncode == 0, proc.stderr
    # The probe sleeps 30 s. Anything near that is the interpreter waiting on
    # ~QThreadPool; anything near 1 s is the process declining to.
    assert elapsed < 10.0, (
        f"the process took {elapsed:.2f}s to exit after a 100 ms stop() — "
        f"the wait was deferred, not removed"
    )


@pytest.mark.integration
def test_a_process_that_reaps_does_not_pay_for_shutdown(tmp_path) -> None:
    """Acceptance (2) of LWSM-1117, asserted rather than observed.

    The reviewer's finding was a *measurement*: the suite's process wall was
    3.3 s longer than the time pytest reported, all of it spent after pytest had
    finished, in `~QThreadPool`. A number in a report rots; this asserts it.

    The script stamps its own last line, and the test compares that stamp to
    when the process actually exited — so what is measured is **shutdown cost
    alone**, with interpreter startup and the work itself excluded. Comparing
    total wall to a literal would fold in PySide6's ~0.3 s import and make the
    threshold meaningless.

    Not merged with `test_the_process_exits_promptly_when_a_probe_is_abandoned`:
    that one covers the `os._exit` path, which only the entry point may take.
    This one covers every other caller, which must reach shutdown holding
    nothing rather than exit early.
    """
    script = tmp_path / "reap_then_exit.py"
    script.write_text(
        textwrap.dedent(
            """
            import os, sys, threading, time
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from pathlib import Path
            from PySide6.QtCore import QCoreApplication
            from lwsm import controller as cm
            from lwsm.controller import ProjectController
            from lwsm.ports import PortSnapshot
            from lwsm.registry import ProjectRecord

            cm.STOP_WAIT_MS = 100
            GATE = threading.Event()

            class GatedProbe:
                def snapshot(self):
                    GATE.wait(timeout=30)
                    return PortSnapshot(frozenset())

            app = QCoreApplication([])
            record = ProjectRecord(
                path=Path("/srv/a"), name="a", port=5005, port_override=None
            )
            controller = ProjectController([record], GatedProbe())
            controller.poll_once()
            time.sleep(0.3)
            controller.stop()          # bounded at 100 ms, abandons the pool
            GATE.set()                 # the probe can now finish
            cm.wait_for_abandoned_probes(5000)
            print(f"SCRIPT_END {time.time():.6f}", flush=True)
            """
        )
    )

    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90
    )
    exited_at = time.time()

    assert proc.returncode == 0, proc.stderr
    stamp = [ln for ln in proc.stdout.splitlines() if ln.startswith("SCRIPT_END")]
    assert stamp, f"the script did not reach its end: {proc.stdout!r} {proc.stderr!r}"
    shutdown_cost = exited_at - float(stamp[0].split()[1])

    # 0.5 s is the acceptance's own figure. Without the reap this is the
    # remainder of the probe's 30 s wait.
    assert shutdown_cost < 0.5, (
        f"the process spent {shutdown_cost:.2f}s after its last line — the "
        f"abandoned pool reached interpreter shutdown still holding a thread"
    )


@pytest.mark.integration
def test_an_unreaped_probe_says_so_before_the_process_blocks(tmp_path) -> None:
    """The hang is not preventable here, so it is at least diagnosable.

    A caller that neither exits nor reaps still blocks in `~QThreadPool`, and
    nothing can change that from inside a library: the only escape is `os._exit`
    with an exit code this code cannot see. What the `atexit` guard changes is
    that the process says why *before* it stops responding, instead of dying
    silently after its last line — which took three probe cycles and a
    three-minute kill to identify on 2026-08-07.

    The probe finishes at 3 s so this test terminates. That is the one thing the
    real failure does not do, and it is why the assertion is on the message
    rather than on the timing.
    """
    script = tmp_path / "never_reap.py"
    script.write_text(
        textwrap.dedent(
            """
            import os, sys, time
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from pathlib import Path
            from PySide6.QtCore import QCoreApplication
            from lwsm import controller as cm
            from lwsm.controller import ProjectController
            from lwsm.ports import PortSnapshot
            from lwsm.registry import ProjectRecord

            cm.STOP_WAIT_MS = 100

            class SlowProbe:
                def snapshot(self):
                    time.sleep(3)
                    return PortSnapshot(frozenset())

            app = QCoreApplication([])
            record = ProjectRecord(
                path=Path("/srv/a"), name="a", port=5005, port_override=None
            )
            controller = ProjectController([record], SlowProbe())
            controller.poll_once()
            time.sleep(0.3)
            controller.stop()   # abandons the pool; neither reaped nor exited
            """
        )
    )

    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90
    )

    assert "never returned and were not reaped" in proc.stderr, (
        f"the process blocked with no explanation: {proc.stderr!r}"
    )
    assert "wait_for_abandoned_probes" in proc.stderr, (
        "the warning must name the way out, or it only reports the symptom"
    )


def test_stop_is_bounded_when_a_probe_never_returns(
    qtbot, controllers, monkeypatch
) -> None:
    """`§ 6` promises a stale display when a probe never returns. It does not
    promise an app that cannot be quit."""
    monkeypatch.setattr(controller_module, "STOP_WAIT_MS", 100)
    probe = FakeProbe(5005)
    gate = threading.Event()
    probe.gate = gate
    controller = build(controllers, [record("a")], probe)
    controller.poll_once()

    started = time.perf_counter()
    controller.stop()
    elapsed = time.perf_counter() - started

    # Against the patched budget, not a literal: `< 2.0` with the budget at
    # 100 ms was a 20x-loose threshold that a 1.9 s stop() would pass
    # (LWSM-1109). 5x leaves room for a loaded machine and nothing else.
    budget = controller_module.STOP_WAIT_MS / 1000
    assert elapsed < budget * 5, (
        f"stop() blocked for {elapsed:.2f}s against a {budget:.2f}s budget"
    )

    # Release the fake AFTER the assertion, so the abandoned pool can go idle
    # and the session-wide reaper can drop it. Left unset, this test leaked a
    # blocked thread into the rest of the run and the whole suite paid for it in
    # `~QThreadPool` at interpreter shutdown — 2.6 s that pytest's own number
    # cannot see, because it is spent after pytest has finished (LWSM-1117).
    # `FakeProbe.gate.wait` has a 5 s timeout, which is the *only* reason that
    # was 2.6 s rather than forever.
    gate.set()
    controller_module.wait_for_abandoned_probes(2000)


def test_wait_for_abandoned_probes_reaps_a_pool_whose_probe_finished(
    qtbot, controllers, monkeypatch
) -> None:
    """The non-exiting half of the bound, for every caller that is not `run()`.

    `exit_without_waiting_for_abandoned_probes` is an `os._exit` and so belongs
    only to the entry point. Everything else — this suite, a future embedder, a
    reload path — needs a way to *not be holding* an abandoned pool when the
    interpreter shuts down, because there it is joined with no timeout at all.
    """
    monkeypatch.setattr(controller_module, "STOP_WAIT_MS", 100)
    probe = FakeProbe(5005)
    gate = threading.Event()
    probe.gate = gate
    controller = build(controllers, [record("a")], probe)
    controller.poll_once()
    controller.stop()

    assert controller_module.wait_for_abandoned_probes(100) == 1, (
        "a pool whose probe is still blocked must be reported as live"
    )

    gate.set()

    assert controller_module.wait_for_abandoned_probes(2000) == 0
    assert controller_module._ABANDONED == [], "the reaped pool was not dropped"


def test_start_polling_polls_immediately(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.start_polling()

    # Not left to the timer, which would leave the window blank for a second.
    assert controller.rows()[0].status is ProjectStatus.RUNNING


# --- LWSM-1113: the wiring, not just the helper -------------------------------
#
# Every test below reddens when a *shipped* line is deleted. Each was verified
# by deleting that line and watching the named test fail; before them, all three
# deletions left the full suite green (§ T9).


class FailingProbeThatSignalsCompletion:
    """`FailingProbe`, plus the `finished` event the stop() tests need.

    Kept separate rather than folded into `FailingProbe`: the existing failure
    tests drive the probe through `drain`, which waits on `calls`, and adding an
    event they never clear would be state nobody resets.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.finished = threading.Event()

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        try:
            raise ProbeError("socket table unavailable")
        finally:
            self.finished.set()


class RecoveringProbe:
    """Fails a fixed number of times, then succeeds."""

    def __init__(self, failures: int) -> None:
        self.calls = 0
        self._failures = failures

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        if self.calls <= self._failures:
            raise ProbeError("socket table unavailable")
        return PortSnapshot(frozenset({5005}))


def test_no_failure_is_delivered_after_stop(qtbot, controllers) -> None:
    """INV-16's failure twin, which nothing covered.

    INV-16 says *no* snapshot reaches the controller again, and
    `test_no_snapshot_is_delivered_after_stop` drives only a successful probe —
    so `_on_snapshot`'s `_stopped` guard was pinned and `_on_probe_error`'s was
    not. Deleting the latter left all 150 tests green (LWSM-1113).

    It is also the likelier of the two on the path that matters: a probe which
    outlives `stop()` is usually one that ends by failing. Unguarded, the late
    failure clears `_in_flight`, logs, and reaches `_maybe_emit` — which emits
    unconditionally while `_emitted_once` is False, straight into
    `MainWindow._sync_rows` after teardown.

    Shaped like its successful twin: the probe is allowed to **complete** before
    `stop()`, so the emit is already posted and no disconnect can recall it.
    """
    probe = FailingProbeThatSignalsCompletion()
    controller = build(controllers, [record("a")], probe)
    emissions: list[int] = []
    controller.projects_changed.connect(lambda: emissions.append(1))

    controller.poll_once()
    assert probe.finished.wait(timeout=5), "the probe never ran"
    # Let the emit be posted without spinning the loop that would deliver it.
    time.sleep(0.05)

    controller.stop()
    assert emissions == [], "nothing is dispatched before the loop spins"

    qtbot.wait(200)
    assert emissions == [], "a probe failure arrived after stop() returned"


def test_a_task_whose_signaller_is_gone_reports_rather_than_raises(caplog) -> None:
    """INV-4c's *outer* layer, which fires for real and was untested.

    A task abandoned by `stop()` can outlive the QObject its signals live on, so
    `emit` raises `RuntimeError: Signal source has been deleted` — from outside
    the inner clause, which is how it escaped `run()` before LWSM-1073. PySide6
    swallows what escapes `run()`, so the regression would come back silently:
    a traceback on stderr, exit 0, and no signal. Deleting the outer clause left
    all 150 tests green (LWSM-1113).

    Destroying the parent destroys the child signaller with it, which is the
    real teardown order — the QApplication outlives neither.
    """
    from PySide6.QtCore import QObject

    from lwsm.controller import _SnapshotSignals, _SnapshotTask

    owner = QObject()
    task = _SnapshotTask(FakeProbe(5005), _SnapshotSignals(owner))
    del owner
    gc.collect()

    with caplog.at_level(logging.DEBUG, logger="lwsm.controller"):
        task.run()

    assert any("no live signaller" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_a_success_reports_the_suppressed_count(qtbot, controllers, caplog) -> None:
    """`§ 6` promises the count on three occasions; only two were tested.

    The suppressed count is reported "when the message changes, when a poll
    **succeeds**, and on `stop()`". The change and stop() halves each redden a
    test; the success half did not — deleting `_flush_repeated_error` from
    `_on_snapshot` left all 150 tests green (LWSM-1113).

    It is the half that matters for a recovering machine: without it, a failure
    that returns after a recovery is folded into the old count instead of being
    logged as news.
    """
    probe = RecoveringProbe(failures=3)
    controller = build(controllers, [record("a")], probe)

    with caplog.at_level(logging.WARNING, logger="lwsm.controller"):
        # One logged failure, then two suppressed.
        drain(qtbot, controller, probe, 3)
        caplog.clear()
        controller.poll_once()
        qtbot.waitUntil(lambda: probe.calls >= 4, timeout=2000)
        qtbot.wait(10)

    assert any("repeated 2 more times" in r.getMessage() for r in caplog.records), (
        "the recovery did not report the suppressed run: "
        f"{[r.getMessage() for r in caplog.records]}"
    )
