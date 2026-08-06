"""LWSM-1005 INV-3, INV-4, INV-4b, INV-5, INV-11, INV-12, INV-16.

The controller's whole job is to derive status from observation and say so
once. Every test here injects a fake probe, which the `SupportsSnapshot`
Protocol makes the declared contract rather than a duck-typing accident.

Marked `gui`: a QTimer, QThreadPool and queued cross-thread signals all need a
Qt application object, which `qtbot` supplies (`docs/standards/testing.md
§ T6`).
"""

from __future__ import annotations

import logging
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

    def snapshot(self) -> PortSnapshot:
        self.calls += 1
        self.threads.append(threading.get_ident())
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return PortSnapshot(frozenset(self.listening))


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


# --- LWSM-1073: stop() must actually stop, promptly, and only itself ----------


def test_no_snapshot_is_delivered_after_stop(qtbot, controllers) -> None:
    """INV-16 passed on its wording while failing its stated purpose.

    `waitForDone` waits for `run()` to *finish*, but the emit happens inside
    `run()` over a queued connection — so the event is already posted and is
    dispatched on the next event-loop spin, into a controller the app has
    already torn down. `mainwindow.py` connects that signal, so the late
    delivery re-enters the window's widgets after teardown.
    """
    probe = FakeProbe(5005)
    probe.gate = threading.Event()
    controller = build(controllers, [record("a")], probe)
    emissions: list[int] = []
    controller.projects_changed.connect(lambda: emissions.append(1))

    controller.poll_once()
    probe.gate.set()
    controller.stop()
    assert emissions == [], "nothing is dispatched before the loop spins"

    # One spin is all it took to reproduce the late delivery.
    qtbot.wait(200)
    assert emissions == [], "a snapshot arrived after stop() returned"


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


def test_stop_is_bounded_when_a_probe_never_returns(
    qtbot, controllers, monkeypatch
) -> None:
    """`§ 6` promises a stale display when a probe never returns. It does not
    promise an app that cannot be quit."""
    monkeypatch.setattr(controller_module, "STOP_WAIT_MS", 100)
    probe = FakeProbe(5005)
    probe.gate = threading.Event()  # never set
    controller = build(controllers, [record("a")], probe)
    controller.poll_once()

    started = time.perf_counter()
    controller.stop()
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"stop() blocked for {elapsed:.2f}s on a hung probe"


def test_start_polling_polls_immediately(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.start_polling()

    # Not left to the timer, which would leave the window blank for a second.
    assert controller.rows()[0].status is ProjectStatus.RUNNING
