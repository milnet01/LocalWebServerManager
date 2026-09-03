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
import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path

import pytest
from shiboken6 import isValid

from lwsm import controller as controller_module
from lwsm.controller import ProjectController, ProjectStatus
from lwsm.ports import PortSnapshot, ProbeError
from lwsm.registry import ProjectRecord
from lwsm.supervisor import (
    MAX_LOG_BYTES,
    LauncherUntrusted,
    StopOutcome,
    Supervisor,
    launcher_fingerprint,
)

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


def test_a_probe_failure_clears_the_managed_flag(qtbot, controllers) -> None:
    """`managed` is a claim about the socket table, so an outage must drop it.

    Statuses are held through a failed probe (INV-4b) and `_managed` was held
    with them, having no line of its own. But it gates Open-in-browser, and a
    stranger can take the port during the outage — which is the
    localhost-credibility shape ADR-0004 was written to close, reached through
    staleness rather than `chdir()`. Its safe direction is "a holder we cannot
    name is not ours" (LWSM-1231).

    The emission is asserted too, not just the flag: `_maybe_emit` compares
    statuses alone, so a cleared flag nothing repainted would leave the buttons
    exactly as they were.
    """
    our_pid = os.getpid()

    class OurSupervisor:
        def running(self) -> dict:
            return {Path("/srv/a"): object()}

        def owns_pid(self, project: Path, pid: int) -> bool:
            return pid == our_pid

        def exited(self, project: Path) -> bool:
            return False

        def is_stopping(self, project: Path) -> bool:
            return False

    class FlakyHolderProbe:
        def __init__(self) -> None:
            self.fail = False

        def snapshot(self) -> PortSnapshot:
            if self.fail:
                raise ProbeError("gone")
            return PortSnapshot(frozenset({5005}), {5005: our_pid})

    probe = FlakyHolderProbe()
    controller = ProjectController([record("a")], probe, OurSupervisor())
    controllers.append(controller)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].managed, "our own pid holds the port"

    probe.fail = True
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    row = controller.rows()[0]
    assert row.status is ProjectStatus.RUNNING, "INV-4b: the status is held"
    assert not row.managed, "but ownership is not something we can still claim"


def test_an_overridden_project_still_sitting_on_its_declared_port_reads_running(
    qtbot, controllers
) -> None:
    """ADR-0004: "a project's `declared` port is probed as well as its
    effective one, whenever the two differ".

    `effective_port` is the override once one is set, so the declared port was
    never looked at. The ADR spells out this exact consequence: a non-adopting
    project asked for 5999 is still on its hard-coded 5005, nothing holds 5999,
    the table says `stopped` — "then Start would cheerfully spawn a duplicate".

    Reported as plain `running`, not as a distinct state: `running (wrong
    port)` is one of the four states P06's model adds, and inventing it here
    would be that item rather than this one. Plain `running` is true at
    today's granularity and is what stops the duplicate.
    """
    stubborn = replace(record("a", 5005), port_override=5999)
    # Only the DECLARED port is held: the project ignored the override.
    controller = build(controllers, [stubborn], FakeProbe(5005))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows()[0].status is ProjectStatus.RUNNING, (
        "nothing holds the override, so the project read as stopped and Start "
        "would have spawned a second server beside the one already running"
    )


def test_starting_a_second_project_does_not_make_the_first_read_stopped(
    qtbot, controllers
) -> None:
    """The overlay is one slot, and `design.md` says so deliberately.

    So Start A then Start B replaces A's label while A's child is alive and
    still binding, and A fell back to `stopped` — with Start enabled, which
    only earns an `AlreadyRunning` refusal. Two servers at once is the app's
    whole premise, so this is an ordinary path rather than a corner.

    The fix is not a second overlay slot, which would contradict that
    contract. ADR-0004 already defines `starting` as a DERIVED state — "live
    child, effective port held by nobody, child holds no port" — so the
    fallback is a derivation the ADR asks for, and the overlay stays exactly
    one project wide.

    Two projects on purpose: with one, "A still reads starting" cannot be told
    from "the overlay is still on A".
    """
    supervisor = FakeSupervisor()
    controller = supervised(
        controllers,
        # `startable`, not `record`: a spawn needs an argv, and without one
        # `start_project` refuses before the supervisor ever hears about it.
        [startable("a", 5005), startable("b", 6006)],
        FakeProbe(),
        supervisor,
    )

    controller.start_project(Path("/srv/a"))
    controller.start_project(Path("/srv/b"))
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    first = next(row for row in controller.rows() if row.name == "a")
    assert first.status is ProjectStatus.STARTING, (
        "A's child is alive and has not bound its port yet, and A read "
        f"{first.status.value} — with Start offered on a live server"
    )


class SwitchableProbe:
    """A probe the test turns on and off between polls."""

    def __init__(self) -> None:
        self.fail: str | None = None

    def snapshot(self) -> PortSnapshot:
        if self.fail is not None:
            raise ProbeError(self.fail)
        return PortSnapshot(frozenset({5005}))


def test_a_probe_failure_is_reported_once_and_so_is_the_recovery(
    qtbot, controllers
) -> None:
    """`design.md`: "Every failure has a visible home... Nothing is swallowed."

    `_on_probe_error` correctly holds the previous statuses (INV-4b) and then
    called `_maybe_emit(self._statuses)` — passing the SAME object it compares
    against, so `previous != self._statuses` could never be true and no signal
    was emitted at all. Under `hidepid=2`, an LSM, or a container with no
    /proc, every row then showed plausible stale data for the rest of the
    session with only `app.log` as evidence.

    Reported through `action_failed` with no path, which `_report_failure`
    already routes to the status bar rather than to a row — the failure is
    about the whole socket table, not about one project.

    The recovery is asserted too: a message that appears and never clears is
    its own defect, and the suppression that stops 86,400 log lines a day
    (LWSM-1079) must not also stop the second, different message.
    """
    probe = SwitchableProbe()
    controller = build(controllers, [record("a")], probe)
    reported: list[tuple[object, str]] = []
    controller.action_failed.connect(lambda path, text: reported.append((path, text)))

    # A good poll first: the first-poll branch emits unconditionally, so a
    # failure there would pass whether or not this works.
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert reported == []

    probe.fail = "AccessDenied"
    with qtbot.waitSignal(controller.action_failed, timeout=2000):
        controller.poll_once()
    assert len(reported) == 1, reported
    assert reported[0][0] is None, "the whole table is unreadable, not one row"
    assert "AccessDenied" in reported[0][1]

    # The same failure again says nothing new.
    controller.poll_once()
    qtbot.wait(50)
    assert len(reported) == 1, f"the repeat was reported too: {reported}"

    probe.fail = None
    with qtbot.waitSignal(controller.action_failed, timeout=2000):
        controller.poll_once()
    assert len(reported) == 2, reported
    assert reported[1][0] is None


def test_a_later_claimant_on_a_port_is_refused_at_start(qtbot, controllers) -> None:
    """ADR-0005 promises BOTH halves and only the flag existed.

    "every later claimant is marked *port claimed by <other project>* and its
    Start is refused with that message until the user re-ports one of them.
    No silent winner, and no state where two rows both claim to own one port."

    The flag is computed in `registry` at merge time and goes nowhere: nothing
    persists it, nothing renders it per row, and the only port check at Start
    is the supervisor's LIVE-SOCKET pre-flight, which fires only when the other
    project is already running — precisely not the state this rule is about
    (LWSM-1205).

    The tie-break is the ADR's own: earliest `added` wins, so the SECOND
    project is the one refused. Asserted in both directions, because a refusal
    that fired on the winner too would look the same from one assertion.
    """
    first = replace(startable("first", 5005), added="2026-01-01T00:00:00Z")
    second = replace(startable("second", 5005), added="2026-06-01T00:00:00Z")
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [first, second], FakeProbe(), supervisor)
    messages: list[str] = []
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    controller.start_project(Path("/srv/second"))

    assert messages, "the later claimant was started with no refusal at all"
    assert "5005" in messages[0] and "first" in messages[0], messages
    assert not supervisor.started, "it spawned anyway"

    controller.start_project(Path("/srv/first"))
    assert supervisor.started, "the earliest claimant owns the port and may start"


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
    (INV-5), which is what makes each iteration wait for a *delivered snapshot*
    rather than for a sleep. That is not the same as a completed poll — the
    emission happens inside `run()` — so the pool is drained separately below.
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
        """Count objects of `kind` whose **C++** object is still alive.

        `gc.get_objects()` alone answers a different question, and that is what
        made this test load-flaky (LWSM-1158). PySide keeps a Python reference
        to every runnable it has been handed — the referrers of a survivor are
        a `list` and the `QThreadPool` itself — and purges those entries
        lazily. Measured 2026-08-20 under CPU load: 1, 26, 54 and 163 surviving
        wrappers across otherwise identical runs, with `isValid` reporting
        **0** live C++ objects every time. So the old count tracked PySide's
        purge cadence, not this code's behaviour, and a loaded machine looked
        exactly like the leak the test exists for.

        `isValid` asks what the test means: has the pool deleted the task, or
        is it still alive? Under `setAutoDelete(False)` it never is, which is
        the defect — and that is 200 here, not a handful.
        """
        gc.collect()
        return sum(1 for obj in gc.get_objects() if type(obj) is kind and isValid(obj))

    # Measured as GROWTH, not as an absolute count. `gc.get_objects()` is
    # session-global, and every other controller alive anywhere in the run holds
    # a signaller of its own — so `signals <= 1` was really asserting "this is
    # the only controller in the process", which is true only by accident of how
    # many windows the rest of the suite happens to be holding. It broke on
    # 2026-08-14 when LWSM-1131 added rescan-window tests, passing in isolation
    # and failing in a full run, which reads exactly like a leak and is not one.
    # The original defect was one task and one signaller **per tick**, so a delta
    # over 200 polls still catches it by a factor of 200.
    before_tasks = live(controller_module._SnapshotTask)
    before_signals = live(controller_module._SnapshotSignals)

    polls = 200
    for _ in range(polls):
        with qtbot.waitSignal(controller.projects_changed, timeout=2000):
            controller.poll_once()
    assert probe.calls == polls

    # Wait for the POOL, not for a signal. The task emits from *inside*
    # `run()`, and the pool deletes it only once `run()` **returns**, so
    # `waitSignal` hands control back with that task still legitimately alive.
    # Under load the pool carries a backlog of them. `stop()` is the drain —
    # the controller's own bounded `waitForDone`, so this asks for quiescence
    # without reaching into the private pool — and after it a live task is a
    # genuine survivor rather than one still doing its job.
    controller.stop()

    # Zero, not INV-12's one: that invariant bounds what is outstanding while
    # the controller runs, and the drain above has just ended it. Nothing may
    # survive a quiesced pool.
    #
    # Deleting that drain leaves this green — measured 2026-08-20, 0 of 6
    # mutant runs red under load and 0 of 3 quiet, at this ceiling and at
    # `<= 1`. It is kept anyway, on the distinction the § T9 note in
    # `CLAUDE.md` draws: a surviving mutant proves the race is hard to lose,
    # not that there is none. Without the drain, "zero" holds only because the
    # last task's `run()` has always returned by the time the count is taken —
    # which is the same timing assumption this item exists to remove. The
    # drain makes it a guarantee rather than an observation.
    #
    # `polls // 10` had already been widened once, from `<= 1` on 2026-08-14,
    # to absorb exactly the wrapper-purge lag `live()` no longer counts — and
    # widening it again to clear a backlog of 182 would have taken it past the
    # 200 the original defect produces, i.e. past asserting anything at all.
    ceiling = 0
    tasks = live(controller_module._SnapshotTask) - before_tasks
    signals = live(controller_module._SnapshotSignals) - before_signals
    assert tasks <= ceiling, f"{tasks} more live tasks after {polls} completed polls"
    assert signals <= ceiling, (
        f"{signals} more live signallers after {polls} completed polls"
    )


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


def test_the_shipped_stop_budget_is_pinned() -> None:
    """The budget tests all substitute their own value, so none pins the real one.

    Both of them patch `STOP_WAIT_MS` and then assert against
    `controller_module.STOP_WAIT_MS`, which makes INV-16's "returned within
    `STOP_WAIT_MS`" true for *any* value: 2000 → 60000 left the whole suite
    green (known-issue-007). Patching is right — a test must not wait two real
    seconds — so the shipped value needs its own assertion rather than a
    rewrite of those.

    2000 ms is a user-visible quit delay, justified in spec § 4.3 as ~60×
    headroom over a measured 33.4 ms probe. This pins both halves of that
    sentence, so a future edit has to change the reasoning too.
    """
    assert controller_module.STOP_WAIT_MS == 2000
    assert controller_module.STOP_WAIT_MS / 33.4 > 50, (
        "spec § 4.3 justifies this budget as ~60x headroom over a 33.4 ms "
        "probe; that reasoning no longer holds"
    )


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


# --- LWSM-1010: the buttons and the optimistic overlay ------------------------


class FakeTrust:
    def __init__(self) -> None:
        self.confirmed: list[tuple[Path, str]] = []

    def confirm(self, project: Path, fingerprint: str) -> None:
        self.confirmed.append((project, fingerprint))


class FakeSupervisor:
    """A supervisor whose every outcome the test chooses.

    `SupportsSupervision` is why this is a contract rather than a duck-typing
    workaround: a real `Supervisor` here would spawn processes for a test about
    an overlay.
    """

    def __init__(self, refusal: Exception | None = None) -> None:
        self.trust = FakeTrust()
        self.refusal = refusal
        self.started: list[tuple[Path, tuple[str, ...], int | None]] = []
        self.stopped: list[Path] = []
        self._running: dict[Path, object] = {}
        self.futures: list[Future] = []
        # The child spawned and then died on its own. A real `Supervisor`
        # answers this from a non-reaping liveness check; here the test says so.
        self.exited_projects: set[Path] = set()
        # A stop the supervisor has reserved but not finished (LWSM-1191).
        self.stopping_projects: set[Path] = set()

    def start(self, project, name, argv, port):
        if self.refusal is not None:
            raise self.refusal
        self.started.append((project, tuple(argv), port))
        self._running[project] = object()
        return self._running[project]

    def stop_async(self, project):
        self.stopped.append(project)
        self._running.pop(project, None)
        future: Future = Future()
        self.futures.append(future)
        return future

    def running(self):
        return dict(self._running)

    def exited(self, project):
        return project in self.exited_projects

    def is_stopping(self, project):
        return project in self.stopping_projects


def supervised(controllers, records, probe, supervisor):
    controller = ProjectController(records, probe, supervisor)
    controllers.append(controller)
    return controller


def startable(name: str = "a", port: int | None = 5005) -> ProjectRecord:
    return ProjectRecord(
        path=Path(f"/srv/{name}"), name=name, port=port, argv=("./start.sh",)
    )


def test_start_shows_starting_before_the_next_poll(qtbot, controllers) -> None:
    """The whole point of the overlay: the button feels responsive.

    Set only on a spawn that actually happened — marking a project `starting`
    and then reporting a refusal would leave the row claiming a transition
    nothing began, and `starting` is not a state probing can disagree with.
    """
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.start_project(Path("/srv/a"))

    assert controller.rows()[0].status is ProjectStatus.STARTING
    assert supervisor.started == [(Path("/srv/a"), ("./start.sh",), 5005)]


def test_a_slow_start_keeps_the_overlay_until_the_port_appears(
    qtbot, controllers
) -> None:
    """ "There is no timeout on it: a slow start keeps the overlay until a poll
    disagrees."

    A server that has not finished binding reads as `stopped`, so clearing the
    overlay on any derived state would drop it on the very next tick and the row
    would flicker straight back — protecting nothing. This is the discriminating
    case, and a merge of the two rules passes without it.
    """
    probe = FakeProbe()
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], probe, supervisor)
    controller.start_project(Path("/srv/a"))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.STARTING, (
        "a poll reporting 'not bound yet' must not discard a starting overlay"
    )

    probe.listening.add(5005)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING


def test_a_port_less_project_does_not_freeze_on_starting(qtbot, controllers) -> None:
    """`port is None` means *unknown, never a guess*, so nothing can ever report
    `running` for this row — `_classify` returns UNKNOWN, which is neither of
    `_OVERLAY_SETTLES_ON`'s targets.

    Before LWSM-1133 the row read `starting` for the life of the session with
    all four buttons dead. The overlay covers the gap before a port binds; a
    project with no port has no such gap, so the honest answer is already
    available. Not a timeout — nothing is being waited out (ADR-0004
    § Slowness is not failure); it settles on the observation that there is
    nothing to observe.
    """
    supervisor = FakeSupervisor()
    controller = supervised(
        controllers, [startable(port=None)], FakeProbe(), supervisor
    )
    controller.start_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STARTING

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows()[0].status is ProjectStatus.UNKNOWN
    assert controller._overlay is None


def test_a_port_less_project_does_not_freeze_on_stopping(qtbot, controllers) -> None:
    """The mirror, and it needs its own case.

    `_on_stopped` deliberately leaves a successful stop's overlay for a poll to
    clear, because the port is what the row reports — but there is no port here,
    so the poll it defers to could never clear it either.
    """
    supervisor = FakeSupervisor()
    controller = supervised(
        controllers, [startable(port=None)], FakeProbe(), supervisor
    )
    controller.start_project(Path("/srv/a"))
    controller.stop_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STOPPING
    supervisor.futures[0].set_result(StopOutcome(exit_code=0))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows()[0].status is ProjectStatus.UNKNOWN
    assert controller._overlay is None


def test_the_overlay_covers_exactly_one_project(qtbot, controllers) -> None:
    """It lives on the controller and covers one row, so it cannot become the
    second store `design.md § State management` forbids."""
    supervisor = FakeSupervisor()
    controller = supervised(
        controllers, [startable("a"), startable("b", 6006)], FakeProbe(), supervisor
    )

    controller.start_project(Path("/srv/a"))
    controller.start_project(Path("/srv/b"))

    statuses = [row.status for row in controller.rows()]
    assert statuses.count(ProjectStatus.STARTING) == 1
    assert statuses[1] is ProjectStatus.STARTING, "the later Start owns the overlay"


def test_a_project_with_no_launcher_says_so_rather_than_failing(
    qtbot, controllers
) -> None:
    """The launcher is a DETECTED field, so the answer is a rescan — and saying
    that is more use than "failed to start"."""
    controller = supervised(
        controllers,
        [ProjectRecord(path=Path("/srv/a"), name="a", port=5005)],
        FakeProbe(),
        FakeSupervisor(),
    )
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    controller.start_project(Path("/srv/a"))

    assert messages and "Rescan" in messages[0]
    assert controller.rows()[0].status is not ProjectStatus.STARTING


def test_an_unconfirmed_launcher_asks_rather_than_failing(qtbot, controllers) -> None:
    """ADR-0003 § Trust. The refusal carries the resolved path, the exact argv
    and the fingerprint, because a confirmation showing a friendly summary is
    security theatre."""
    refusal = LauncherUntrusted(Path("/srv/a/start.sh"), ("./start.sh",), "abc123")
    supervisor = FakeSupervisor(refusal=refusal)
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    asked: list[tuple] = []
    controller.confirmation_required.connect(lambda p, r: asked.append((p, r)))
    failures: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: failures.append(text))

    controller.start_project(Path("/srv/a"))

    assert asked == [(Path("/srv/a"), refusal)]
    assert failures == [], "an unconfirmed launcher is not a failure"
    assert controller.rows()[0].status is not ProjectStatus.STARTING

    supervisor.refusal = None
    controller.confirm_and_start(Path("/srv/a"), refusal.fingerprint)
    assert supervisor.trust.confirmed == [(Path("/srv/a"), "abc123")]
    assert supervisor.started


def test_stopping_a_project_this_manager_did_not_start_is_refused(
    qtbot, controllers
) -> None:
    """A `running (foreign)` project has no handle to signal through, and
    ADR-0003 forbids signalling a bare PID. The foreign-stop path is its own
    item; until then this reports rather than pretending."""
    controller = supervised(
        controllers, [startable()], FakeProbe(5005), FakeSupervisor()
    )
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    controller.stop_project(Path("/srv/a"))

    assert messages and "not started by this manager" in messages[0]


def test_stop_shows_stopping_and_a_bound_port_afterwards_only_warns(
    qtbot, controllers
) -> None:
    """The stop runs on a worker, and its outcome arrives on the GUI thread.

    A port still bound after the child is gone is reported and never signalled
    a second time — the `or` ADR-0003 struck, because it fires exactly when our
    child is already reaped and something else holds the port.
    """
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.stop_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STOPPING

    supervisor.futures[0].set_result(
        StopOutcome(port_still_bound=True, warning="port 5005 is still bound")
    )
    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    assert "still bound" in messages[0]


def test_a_restart_starts_only_after_the_stop_has_finished(qtbot, controllers) -> None:
    """Sequenced through the stop's completion, not run back to back: starting
    before the old process released the port is exactly what the pre-flight
    check would then refuse."""
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))
    supervisor.started.clear()

    controller.restart_project(Path("/srv/a"))
    assert supervisor.stopped == [Path("/srv/a")]
    assert supervisor.started == [], "the start must wait for the stop"

    supervisor.futures[0].set_result(StopOutcome(exit_code=0))
    qtbot.waitUntil(lambda: bool(supervisor.started), timeout=2000)
    assert controller.rows()[0].status is ProjectStatus.STARTING


def test_a_stop_that_raises_clears_the_overlay_and_reports(qtbot, controllers) -> None:
    """`concurrent.futures` logs an exception out of a done-callback and drops
    it, so without the catch the row would read `stopping` for the life of the
    session."""
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))
    controller.stop_project(Path("/srv/a"))
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    supervisor.futures[0].set_exception(RuntimeError("the pool fell over"))

    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    assert "could not stop" in messages[0]
    assert controller.rows()[0].status is not ProjectStatus.STOPPING


def test_a_start_that_exits_without_binding_does_not_freeze_on_starting(
    qtbot, controllers
) -> None:
    """ADR-0004's own definition of `failed`: the child exited without ever
    binding.

    The derived status stays `stopped`, which never equals `RUNNING`, so before
    LWSM-1134 the row sat at `starting` permanently and only restarting the app
    recovered it. The evidence was available from the `Supervisor` all along and
    the controller never asked for it.
    """
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STARTING

    supervisor.exited_projects.add(Path("/srv/a"))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller.rows()[0].status is ProjectStatus.STOPPED
    assert controller._overlay is None


def test_a_stop_whose_port_is_still_held_does_not_freeze_on_stopping(
    qtbot, controllers
) -> None:
    """The mirror case: the stop succeeded, and something this manager did not
    start holds the port.

    The derived status therefore reads `running` forever, `STOPPED` is
    unreachable, and the overlay would sit at `stopping` for the life of the
    session.
    """
    probe = FakeProbe()
    probe.listening.add(5005)
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], probe, supervisor)
    controller.start_project(Path("/srv/a"))
    controller.stop_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STOPPING
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    supervisor.futures[0].set_result(
        StopOutcome(
            exit_code=0, port_still_bound=True, warning="port 5005 is still bound"
        )
    )

    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    assert controller._overlay is None

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.RUNNING, (
        "the row falls back to what is actually observable: someone holds it"
    )


def test_a_stop_whose_port_check_failed_still_waits_for_a_poll(
    qtbot, controllers
) -> None:
    """The discriminating case, and the reason the clear is keyed on
    `port_still_bound` rather than on `warning`.

    A warning is also emitted when the probe itself could not be read — there
    the port's state is *unknown*, not held, so nothing terminal has been
    observed and the ordinary settle still applies. Keying on `warning` passes
    the case above and fails this one.
    """
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))
    controller.stop_project(Path("/srv/a"))
    messages: list[str] = []
    # (path, message) since LWSM-1032; these tests assert the message.
    controller.action_failed.connect(lambda _path, text: messages.append(text))

    supervisor.futures[0].set_result(
        StopOutcome(exit_code=0, warning="could not check port 5005 after stopping: x")
    )

    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    assert controller.rows()[0].status is ProjectStatus.STOPPING, (
        "an unreadable probe is not evidence that anything terminal happened"
    )

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.STOPPED


def test_a_stopping_overlay_holds_while_the_dying_child_still_holds_the_port(
    qtbot, controllers
) -> None:
    """The exited-child evidence unsticks a START, and must not touch a STOP.

    Mid-sequence the child is already dead while its port is still bound, and
    the stop has not finished. Clearing on that would drop the row to `running`
    for a tick and then to `stopped` — the flicker `design.md § State
    management` and ADR-0004 exist to prevent. Only the port can say a stop is
    done, which is why `_on_stopped` defers to a poll in the first place.

    Found by mutation: removing the `pending is STARTING` guard left the whole
    suite green.
    """
    probe = FakeProbe()
    probe.listening.add(5005)
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], probe, supervisor)
    controller.start_project(Path("/srv/a"))
    controller.stop_project(Path("/srv/a"))
    assert controller.rows()[0].status is ProjectStatus.STOPPING

    supervisor.exited_projects.add(Path("/srv/a"))

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.STOPPING, (
        "a dead child whose port is still bound has not finished stopping"
    )

    probe.listening.discard(5005)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert controller.rows()[0].status is ProjectStatus.STOPPED


def test_an_overlay_on_a_project_that_leaves_the_list_is_dropped(
    qtbot, controllers
) -> None:
    """A rescan can remove a row. An overlay keyed on a path nothing renders
    would sit there for the life of the session."""
    supervisor = FakeSupervisor()
    controller = supervised(controllers, [startable()], FakeProbe(), supervisor)
    controller.start_project(Path("/srv/a"))

    controller.set_records([startable("b", 6006)])
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert controller._overlay is None


# --- LWSM-1136: the poll is what makes the 5 MB log cap a cap ------------------


@pytest.mark.integration
def test_the_poll_caps_a_running_projects_log(qtbot, controllers, tmp_path) -> None:
    """`rotate_if_needed` had exactly one caller in the whole tree, and it was a
    test.

    So `design.md § Observability`'s "capped at 5 MB with one rotation" and
    LWSM-1009's bullet were both false in the shipped build: a chatty or looping
    server appended to an `O_APPEND` descriptor with no bound until the disk
    filled. A method with no production caller is not a cap, and a test that
    calls it directly cannot tell the two apart — which is what let this ship.

    So this drives the POLL, against a real `Supervisor` and a real child, and
    the controller holds no record for the project at all: the supervisor's own
    running set is what the cap is keyed on, and it must not depend on the row
    happening to be in the list.

    Dies on removing the `self._rotate_logs()` call from `poll_once`.
    """
    project = tmp_path / "chatty"
    project.mkdir()
    launcher = project / "start.sh"
    launcher.write_text(
        "#!/bin/sh\nwhile true; do sleep 0.05; done\n", encoding="utf-8"
    )
    launcher.chmod(0o700)

    supervisor = Supervisor(probe=FakeProbe(), log_dir=tmp_path / "logs")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    managed = supervisor.start(project, name="chatty", argv=["./start.sh"], port=None)
    try:
        # Written through our own descriptor, so the child is alive and still
        # holding its duplicate — a log grown after the start is exactly the case.
        os.pwrite(managed.log_fd, b"x" * (MAX_LOG_BYTES + 1), 0)
        rotated = managed.log_path.with_name(managed.log_path.name + ".1")
        assert not rotated.exists()

        controller = build(controllers, [], FakeProbe())
        controller._supervisor = supervisor
        controller.poll_once()

        assert rotated.exists(), "a poll left the log over the cap"
        assert managed.log_path.stat().st_size < MAX_LOG_BYTES
    finally:
        for path in list(supervisor.running()):
            supervisor.stop(path, grace=0.5)
        supervisor.close()


def test_a_log_that_cannot_be_rotated_does_not_stop_the_poll(
    qtbot, controllers, caplog
) -> None:
    """Contained per project, and as wide as INV-4c's clause.

    `poll_once` runs in a timer slot on the GUI thread, so anything escaping it
    is swallowed by PySide6 — no crash, no dialog, no status change. One
    unreadable log would silently stop every other project being capped AND
    take the tick's probe with it, because the rotation runs before the probe
    is started.

    Dies on narrowing the `except Exception` to `OSError`, and on removing the
    try entirely.
    """

    class ExplodingSupervisor:
        def __init__(self) -> None:
            self.asked: list[Path] = []

        def running(self):
            return {Path("/srv/a"): object(), Path("/srv/b"): object()}

        def exited(self, project):
            return False

        def is_stopping(self, project):
            return False

        def rotate_if_needed(self, project: Path) -> bool:
            self.asked.append(project)
            if project == Path("/srv/a"):
                raise ValueError("a shape no clause names")
            return False

    supervisor = ExplodingSupervisor()
    probe = FakeProbe(5005)
    controller = build(controllers, [record("b", 5005)], probe)
    controller._supervisor = supervisor

    with caplog.at_level(logging.WARNING):
        with qtbot.waitSignal(controller.projects_changed, timeout=2000):
            controller.poll_once()

    assert supervisor.asked == [Path("/srv/a"), Path("/srv/b")], (
        "one project's failure stopped the others being capped"
    )
    assert probe.calls == 1, "the tick's probe never ran"
    assert "could not rotate the log" in caplog.text


# --- LWSM-1165: the poll is what releases a self-exited project's slot ---------


@pytest.mark.integration
def test_the_poll_releases_the_slot_of_a_child_that_exited_on_its_own(
    qtbot, controllers, tmp_path
) -> None:
    """`reap_exited` is only worth anything if something CALLS it once a second.

    The same trap `rotate_if_needed` fell into above: a method with no
    production caller looks exactly like a working one, and its own unit test
    cannot tell the two apart. So this drives the POLL against a real
    `Supervisor` and a real child that exits by itself, and asserts the slot is
    released — which is the user-visible effect, since until it is, every
    Start on that project raises `AlreadyRunning` with Stop and Restart both
    greyed out.

    Dies on removing the `self._reap_exited()` call from `poll_once`.
    """
    project = tmp_path / "crasher"
    project.mkdir()
    launcher = project / "start.sh"
    launcher.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    launcher.chmod(0o700)

    supervisor = Supervisor(probe=FakeProbe(), log_dir=tmp_path / "logs")
    supervisor.trust.confirm(project, launcher_fingerprint(project, ("./start.sh",)))
    supervisor.start(project, name="crasher", argv=["./start.sh"], port=None)
    try:
        deadline = time.monotonic() + 10.0
        while supervisor.running() and time.monotonic() < deadline:
            controller = build(controllers, [], FakeProbe())
            controller._supervisor = supervisor
            controller.poll_once()

        assert not supervisor.running(), "the poll never released the slot"
        # The whole point: there is a route back.
        supervisor.start(project, name="crasher", argv=["./start.sh"], port=None)
    finally:
        for path in list(supervisor.running()):
            supervisor.stop(path, grace=0.5)
        supervisor.close()


# --- LWSM-1018: the poll cadence is a setting ----------------------------------


def test_the_poll_interval_changes_without_stopping_the_timer(controllers) -> None:
    """A new cadence applies to a running poll loop, with no restart.

    The second assertion is the one with teeth. `QTimer.setInterval` is honoured
    on a live timer, so the correct implementation is one line — but a
    stop/setInterval/start version looks equally plausible and silently stops
    polling for good if the restart is ever dropped. Asserting only the interval
    would pass against that.

    Dies on replacing the body with `pass`, and on a stop-without-restart.
    """
    from lwsm.controller import POLL_INTERVAL_MS

    controller = build(controllers, [], FakeProbe())
    controller.start_polling()

    assert controller._timer.interval() == POLL_INTERVAL_MS
    assert controller._timer.isActive()

    controller.set_poll_interval_ms(5000)

    assert controller._timer.interval() == 5000
    assert controller._timer.isActive(), "changing the cadence stopped the poll loop"
