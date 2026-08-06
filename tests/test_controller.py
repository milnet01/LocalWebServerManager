"""LWSM-1005 INV-3, INV-4, INV-4b, INV-5, INV-11, INV-12, INV-16.

The controller's whole job is to derive status from observation and say so
once. Every test here injects a fake probe, which the `SupportsSnapshot`
Protocol makes the declared contract rather than a duck-typing accident.

Marked `gui`: a QTimer, QThreadPool and queued cross-thread signals all need a
Qt application object, which `qtbot` supplies (`docs/standards/testing.md
§ T6`).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

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


def test_start_polling_polls_immediately(qtbot, controllers) -> None:
    probe = FakeProbe(5005)
    controller = build(controllers, [record("a")], probe)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.start_polling()

    # Not left to the timer, which would leave the window blank for a second.
    assert controller.rows()[0].status is ProjectStatus.RUNNING
