"""The one object the UI talks to: polls the socket table, holds the statuses.

Core module — QtCore only, never QtWidgets (`docs/standards/coding.md § O1`),
so the whole poll loop is testable without a display. Contract:
`docs/specs/LWSM-1005-vertical-slice.md § 4.3`.
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from lwsm.ports import PortSnapshot, ProbeError, SupportsSnapshot
from lwsm.registry import ProjectRecord
from lwsm.supervisor import (
    LauncherUntrusted,
    ManagedProcess,
    StopOutcome,
    SupervisorError,
)

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 1000

# How long stop() will wait for an outstanding probe before giving up on it.
# Measured probe time on this machine is 33.4 ms mean over 10 calls, so this is
# roughly 60x headroom. It is a shutdown budget, not a watchdog: nothing here
# times out into a *state* (ADR-0004, "slowness is not failure") — the display
# stays stale, and only the app's ability to quit is bounded.
STOP_WAIT_MS = 2000

# Pools abandoned by stop() because their probe was still running. The list
# exists because ~QThreadPool calls waitForDone() with NO timeout, so letting
# one be destroyed reintroduces exactly the hang the budget above bounds.
#
# It does not make them immortal, and the comment here used to claim it did.
# CPython releases module globals at interpreter shutdown, which destroys these
# pools, which runs that unbounded wait — so holding them *defers* the hang to
# the last moment of the process rather than removing it. Measured before
# LWSM-1100: stop() returned in 0.10 s and the process took 4.16 s to exit
# behind a 4 s probe. `exit_without_waiting_for_abandoned_probes` is the half
# that actually bounds it; this list only keeps the pool alive until then.
_ABANDONED: list[QThreadPool] = []


def wait_for_abandoned_probes(timeout_ms: int = STOP_WAIT_MS) -> int:
    """Reap abandoned pools that have gone idle. Returns how many are still live.

    The other half of the bound, for every caller that is **not** ending the
    process. `exit_without_waiting_for_abandoned_probes` is an `os._exit`, so it
    belongs to the entry point alone — which left this suite, and any future
    embedder or reload path, inheriting the unbounded wait in full (LWSM-1117).

    Two things were measured on 2026-08-07 while closing that, and both are
    worse than the report it came from:

    - The wait is not "~3.3 s", it is **unbounded**. A probe that genuinely
      never returns hung the interpreter indefinitely — killed at three minutes,
      main thread on a futex joining the pool thread. The suite escaped only
      because its fake probe happens to carry a 5 s timeout.
    - **Nothing at the Python level avoids it.** Dropping the reference, holding
      it, reparenting it, and invalidating the Shiboken wrapper were each tried
      against a truly stuck probe; all four hung identically. The C++ destructor
      joins the thread regardless, which is why the only bound is declining to
      run it — and why this function reaps rather than cancels. There is no
      Qt-level way to cancel a running `QRunnable`.

    So a caller that cannot exit the process must instead arrive at interpreter
    shutdown holding nothing. Call this once the work that was abandoned has had
    a chance to finish; a non-zero return means it has not, and that this process
    will block on exit.
    """
    for pool in list(_ABANDONED):
        # waitForDone per pool rather than one shared deadline: the budget is a
        # per-probe allowance, and the common case is a single pool.
        if pool.waitForDone(timeout_ms):
            _ABANDONED.remove(pool)
    return len(_ABANDONED)


def _warn_about_unreaped_probes() -> None:
    """Say so, loudly, if a live abandoned pool reaches interpreter shutdown.

    Deliberately **not** a bound — it cannot be one, for the reason
    `wait_for_abandoned_probes` records: at this point the only escape is
    `os._exit`, and a library that ends the process here would be overriding an
    exit code it cannot see, which is precisely the LWSM-1100 failure (a pytest
    run truncated to 40 % and reported green).

    What it buys is diagnosis. Without it the symptom is a process that stops
    dead after its last line with no output at all — three probe cycles and a
    three-minute kill to identify, on 2026-08-07. With it, the reason is on
    stderr before the hang starts.
    """
    live = [pool for pool in _ABANDONED if pool.activeThreadCount()]
    if not live:
        return
    # print, not log: logging handlers may already be closed at this point, and
    # a message that gets swallowed here is the whole problem.
    print(
        f"lwsm: {len(live)} port probe(s) never returned and were not reaped; "
        "this process will now block in ~QThreadPool, which has no timeout. "
        "An entry point should call exit_without_waiting_for_abandoned_probes; "
        "any other caller should call wait_for_abandoned_probes.",
        file=sys.stderr,
        flush=True,
    )


atexit.register(_warn_about_unreaped_probes)


def exit_without_waiting_for_abandoned_probes(code: int) -> None:
    """End the process now if `stop()` gave up on a probe. Otherwise return.

    `§ 6` promises that a probe which never returns leaves a **stale display**,
    and `stop()`'s budget delivers that much. What neither delivers is the
    exit: the abandoned pool is destroyed during interpreter shutdown, and
    `~QThreadPool` waits for its thread with no timeout. So the app quits when
    the stuck probe says so, which is the outcome the budget exists to prevent.

    There is no Qt-level way to cancel a running `QRunnable` or to keep a
    `QThreadPool` from waiting in its destructor, so the only thing that bounds
    this is declining to run the destructor at all. Called from `main` rather
    than from a hook inside `stop()`, because ending the process is the entry
    point's decision to make and not a core module's — and because `stop()` is
    called by every test fixture.

    Returns untouched on the ordinary path, where nothing was abandoned.
    """
    # A probe that finished after stop() gave up on it leaves an idle pool,
    # whose destructor returns at once. Only a pool still holding a thread is
    # worth skipping the interpreter's own cleanup for.
    _ABANDONED[:] = [pool for pool in _ABANDONED if pool.activeThreadCount()]
    if not _ABANDONED:
        return
    log.warning(
        "%d port probe(s) never returned; exiting without waiting for them",
        len(_ABANDONED),
    )
    # os._exit skips every flush the interpreter would have done, including the
    # one that writes the line above.
    sys.stdout.flush()
    sys.stderr.flush()
    logging.shutdown()
    os._exit(code)


class ProjectStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    # Not a third derived state: it means no observation is available — either
    # there is no port to look at, or no successful poll has completed yet.
    # Calling either "stopped" would assert something nobody looked at (§ O5).
    UNKNOWN = "unknown"
    # Neither of these is derived either: they are the optimistic overlay
    # (`design.md § State management`), which exists so a button feels
    # responsive and is discarded the moment probing disagrees.
    STARTING = "starting"
    STOPPING = "stopping"


# What a Start or a Stop is heading toward. The overlay is discarded when a poll
# reports the state it was waiting for — NOT merely when a poll returns.
#
# The distinction is the whole of "there is no timeout on it: a slow start keeps
# the overlay until a poll disagrees". Clearing `starting` on the first derived
# `stopped` would discard it on the very next tick, since a server that has not
# finished binding reads as stopped — so a slow start would flicker straight back
# to `stopped` and the overlay would protect nothing.
_OVERLAY_SETTLES_ON = {
    ProjectStatus.STARTING: ProjectStatus.RUNNING,
    ProjectStatus.STOPPING: ProjectStatus.STOPPED,
}


class SupportsSupervision(Protocol):
    """What `ProjectController` needs from a `Supervisor`.

    Declared so the fakes the tests inject are the contract rather than a
    duck-typing workaround the annotation contradicts — `ports.SupportsSnapshot`
    for the third time.
    """

    def start(
        self,
        project: Path,
        name: str,
        argv: list[str] | tuple[str, ...],
        port: int | None,
    ) -> ManagedProcess: ...

    def stop_async(self, project: Path) -> Future[StopOutcome]: ...

    def running(self) -> dict[Path, ManagedProcess]: ...

    def exited(self, project: Path) -> bool: ...

    @property
    def trust(self) -> SupportsTrust: ...


class SupportsTrust(Protocol):
    def confirm(self, project: Path, fingerprint: str) -> None: ...


@dataclass(frozen=True)
class RowView:
    """Everything one row renders.

    The UI reads this and nothing else, so MainWindow needs no copy of the
    records — `docs/design.md § Components` gives it no state of its own.
    """

    path: Path
    name: str
    effective_port: int | None
    status: ProjectStatus


class _SnapshotSignals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _SnapshotTask(QRunnable):
    """Takes one snapshot on a pool thread and reports it back by signal.

    The signals live on a composed QObject because QRunnable is not one:
    `issubclass(QRunnable, QObject)` is False under the pinned PySide6 6.11.1,
    and a Signal declared directly on a QRunnable subclass has no `emit`.

    That signaller belongs to the **controller**, not to this task, and is
    reused for every poll. Owning one per task meant it had to outlive `run()`
    for the queued emission to survive — which forced `setAutoDelete(False)`,
    and `QThreadPool.start()` has already transferred ownership to C++, so
    nothing on the Python side could ever free the task afterwards: one task
    and one signaller retained per tick for the life of the process
    (LWSM-1099). A controller-owned signaller lets the pool delete each task
    the moment `run()` returns, which is what `autoDelete` is for.
    """

    def __init__(self, probe: SupportsSnapshot, signals: _SnapshotSignals) -> None:
        super().__init__()
        self._probe = probe
        self.signals = signals

    def run(self) -> None:
        # Two layers, because the emit can fail too. The inner one turns any
        # probe failure into a `failed` signal; the outer one catches the case
        # where there is no longer anything to emit *on*.
        try:
            try:
                snapshot = self._probe.snapshot()
            except ProbeError as exc:
                self.signals.failed.emit(exc)
            except BaseException as exc:
                # An exception escaping run() is swallowed by PySide6 (verified
                # against the pinned 6.11.1, LWSM-1069): the traceback prints to
                # stderr, the process survives at exit 0, and *no* signal is
                # emitted — so the controller's in-flight guard is never cleared
                # and poll_once returns early on every later tick for the life of
                # the process, showing plausible, permanently frozen data.
                # Nothing may leave this method, so the clause is as wide as the
                # language allows rather than as wide as the failures predicted.
                log.exception("the port probe raised an unexpected exception")
                failure = ProbeError(
                    f"the port probe failed: {type(exc).__name__}: {exc}"
                )
                failure.__cause__ = exc
                self.signals.failed.emit(failure)
            else:
                self.signals.done.emit(snapshot)
        except BaseException:
            # A task abandoned by stop() outlives the QApplication that owned
            # every other QObject, so by the time it finishes its signaller can
            # be destroyed and `emit` raises `RuntimeError: Signal source has
            # been deleted`. That was escaping run() — the very thing the inner
            # clause exists to prevent — because the emits sat outside it.
            # There is nobody left to report to, so this is a debug line.
            log.debug("port probe ended with no live signaller", exc_info=True)


class _ActionSignals(QObject):
    """A stop finishing on a worker thread, delivered to the GUI thread.

    `Supervisor.stop_async` returns a `concurrent.futures.Future`, whose
    done-callback runs on the executor's thread. Emitting a Qt signal from a
    `QObject` that lives on the GUI thread is what marshals it back — Qt queues
    a cross-thread emission, which is the same arrangement `_SnapshotSignals`
    uses and the reason a widget is never touched from the worker.
    """

    stopped = Signal(object, object)  # path, StopOutcome | Exception


class ProjectController(QObject):
    projects_changed = Signal()
    # A Start or Stop that could not even be attempted — no launcher, a bound
    # port, a refused launcher. The window puts it in the status bar.
    action_failed = Signal(str)
    # A launcher that has never been confirmed (ADR-0003 § Trust). Carries the
    # `LauncherUntrusted` refusal, which holds the resolved path, the exact argv
    # and the fingerprint — "not security theatre only if it shows what will
    # actually run".
    confirmation_required = Signal(object, object)  # path, LauncherUntrusted

    def __init__(
        self,
        records: list[ProjectRecord],
        probe: SupportsSnapshot,
        supervisor: SupportsSupervision | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._records = records
        self._probe = probe
        # Optional so every pre-LWSM-1010 caller still builds: a controller with
        # no supervisor polls and renders exactly as before, and its Start
        # reports rather than pretending.
        self._supervisor = supervisor
        # The optimistic overlay. ONE project, on the controller rather than in
        # a widget, so it cannot become the second store `design.md § State
        # management` forbids.
        self._overlay: tuple[Path, ProjectStatus] | None = None
        self._action_signals = _ActionSignals(self)
        self._action_signals.stopped.connect(self._on_stopped)
        # Paths whose stop is the first half of a restart.
        self._restarting: set[Path] = set()
        self._statuses: dict[Path, ProjectStatus] = {
            record.path: ProjectStatus.UNKNOWN for record in records
        }
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self.poll_once)
        # One signaller for the controller's whole life, connected once. Both
        # connections are queued: it is created here, on the owning thread,
        # and every emit happens on a pool thread.
        self._signals = _SnapshotSignals(self)
        self._signals.done.connect(self._on_snapshot)
        self._signals.failed.connect(self._on_probe_error)
        # Not the task itself: with autoDelete on, the pool frees it as soon as
        # `run()` returns, so a reference held here would outlive the C++ object.
        self._in_flight = False
        self._emitted_once = False
        # Set by stop(), and the only thing that actually closes INV-16. See
        # stop() for why cutting the connections cannot.
        self._stopped = False
        # Repeated-failure suppression, see _on_probe_error.
        self._last_error: str | None = None
        self._repeated_errors = 0
        # A private pool, not QThreadPool.globalInstance(): shutdown must wait
        # for this controller's own probe and nothing else. One thread, because
        # a tick that arrives while its predecessor is in flight is skipped
        # rather than queued, so a second is never needed.
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

    def rows(self) -> list[RowView]:
        """File order, so rows do not jump between polls."""
        return [
            RowView(
                path=record.path,
                name=record.name,
                effective_port=record.effective_port,
                status=self._status_of(record.path),
            )
            for record in self._records
        ]

    def _status_of(self, path: Path) -> ProjectStatus:
        """The derived status, unless the overlay covers this project."""
        if self._overlay is not None and self._overlay[0] == path:
            return self._overlay[1]
        return self._statuses[path]

    # -- the buttons -----------------------------------------------------

    def start_project(self, path: Path) -> None:
        """Spawn, and show `starting` immediately.

        The overlay is set only on a spawn that actually happened: marking a
        project `starting` and then reporting a refusal would leave the row
        claiming a transition nothing began, which the poll could not correct
        because `starting` is not a state probing can disagree with.
        """
        record = self._record(path)
        if record is None or self._supervisor is None:
            self.action_failed.emit(f"cannot start {path}: nothing to start it with")
            return
        if not record.argv:
            # An honest refusal rather than a guess. The launcher is a detected
            # field, so the answer is a rescan, and saying so is more use than
            # "failed to start".
            self.action_failed.emit(
                f"{record.name} has no launcher recorded — run Rescan first"
            )
            return
        try:
            self._supervisor.start(
                record.path, record.name, record.argv, record.effective_port
            )
        except LauncherUntrusted as refusal:
            # Not a failure: the user has simply not been asked yet. The window
            # shows what would run and calls back in.
            self.confirmation_required.emit(path, refusal)
            return
        except SupervisorError as exc:
            self.action_failed.emit(f"{record.name}: {exc}")
            return
        except OSError as exc:
            # The log file could not be opened. Distinct from SupervisorError
            # because it is about this machine rather than about the project.
            self.action_failed.emit(f"{record.name}: {exc}")
            return
        self._set_overlay(path, ProjectStatus.STARTING)

    def stop_project(self, path: Path) -> None:
        """Signal the group, and show `stopping` immediately.

        The stop itself runs on a worker: a five-second grace period on the UI
        thread would freeze the window (ADR-0003).
        """
        record = self._record(path)
        if record is None or self._supervisor is None:
            self.action_failed.emit(f"cannot stop {path}: nothing is supervising it")
            return
        if path not in self._supervisor.running():
            # A `running (foreign)` project — this manager did not spawn it, so
            # it has no handle to signal through, and ADR-0003 forbids
            # signalling a bare PID. The foreign-stop path is a separate item.
            self.action_failed.emit(
                f"{record.name} was not started by this manager, so it cannot "
                "be stopped from here yet"
            )
            return
        self._set_overlay(path, ProjectStatus.STOPPING)
        future = self._supervisor.stop_async(path)
        future.add_done_callback(lambda done: self._report_stop(path, done))

    def restart_project(self, path: Path) -> None:
        """Stop then start, with the same pre-flight check (ADR-0003).

        Sequenced through the stop's completion rather than run back to back:
        starting before the old process has released the port is exactly what
        the pre-flight check would then refuse.
        """
        if self._supervisor is not None and path in self._supervisor.running():
            self._restarting.add(path)
            self.stop_project(path)
            return
        self.start_project(path)

    def confirm_and_start(self, path: Path, fingerprint: str) -> None:
        """The user has seen the resolved path and argv, and said yes."""
        if self._supervisor is None:
            return
        self._supervisor.trust.confirm(path, fingerprint)
        self.start_project(path)

    def _report_stop(self, path: Path, done: Future[StopOutcome]) -> None:
        """Runs on the WORKER thread. Emits, and does nothing else.

        Anything raising here would be swallowed by `concurrent.futures`, which
        logs it and moves on — so the emission is the whole body, and the work
        happens in the slot on the GUI thread.
        """
        try:
            outcome: object = done.result()
        except BaseException as exc:
            # As wide as the language allows, and for `_SnapshotTask.run`'s
            # reason: an exception escaping a future's done-callback is logged
            # by `concurrent.futures` and dropped, so the overlay would stay set
            # and the row would read `stopping` for the life of the session.
            outcome = exc
        try:
            self._action_signals.stopped.emit(path, outcome)
        except RuntimeError:
            # The controller was torn down while the stop was in flight; there
            # is nobody left to tell. `_SnapshotTask.run`'s outer clause, on a
            # second worker.
            log.debug("a stop finished with no live signaller", exc_info=True)

    def _on_stopped(self, path: Path, outcome: object) -> None:
        if self._stopped:
            return
        pending_restart = path in self._restarting
        self._restarting.discard(path)
        if isinstance(outcome, BaseException):
            self._clear_overlay(path)
            self.action_failed.emit(f"could not stop {path.name}: {outcome}")
            return
        if isinstance(outcome, StopOutcome):
            if outcome.warning:
                # A bound port after a stop is a warning, never a second signal.
                self.action_failed.emit(outcome.warning)
            if outcome.port_still_bound:
                # Terminal (LWSM-1134): our child is gone and something this
                # manager did not start holds the port, so every poll from here
                # reports `running` and `STOPPING`'s target is unreachable.
                # Keyed on `port_still_bound`, NOT on `warning` — a warning is
                # also emitted when the probe could not be read, and there the
                # port's state is unknown rather than held, so nothing terminal
                # has been observed and the ordinary settle must still apply.
                self._clear_overlay(path)
        if pending_restart:
            # Straight into the start, which re-runs the pre-flight check.
            self.start_project(path)
            return
        # The overlay is NOT cleared here: the process is gone, but the port is
        # what the row reports, and only a poll can say it has been released.

    def _record(self, path: Path) -> ProjectRecord | None:
        return next((record for record in self._records if record.path == path), None)

    def _set_overlay(self, path: Path, status: ProjectStatus) -> None:
        self._overlay = (path, status)
        self.projects_changed.emit()

    def _clear_overlay(self, path: Path) -> None:
        if self._overlay is not None and self._overlay[0] == path:
            self._overlay = None
            self.projects_changed.emit()

    def records(self) -> list[ProjectRecord]:
        """The records themselves, for a caller that merges rather than renders.

        `rows()` is what the UI reads; this is what LWSM-1131's rescan hands to
        `registry.merge`. Kept separate so the window still holds no state of
        its own — it asks the controller rather than keeping a second copy that
        could disagree (`design.md § Components`).
        """
        return list(self._records)

    def set_records(self, records: list[ProjectRecord]) -> None:
        """Replace the project list, keeping every status already derived.

        Resetting to `UNKNOWN` across the board would blank the window for up to
        a poll interval after a rescan that changed one row — and `UNKNOWN`
        means *nobody looked*, which would be false of every record that was
        already being polled (`§ O5`).
        """
        self._records = records
        self._statuses = {
            record.path: self._statuses.get(record.path, ProjectStatus.UNKNOWN)
            for record in records
        }
        self.projects_changed.emit()

    def start_polling(self) -> None:
        # Poll immediately rather than leaving the window blank for a second.
        self.poll_once()
        self._timer.start()

    def stop(self) -> None:
        """Timer off, delivery refused, then a bounded wait for the task.

        Without the wait a pool thread emits into a controller being torn
        down — the flake `docs/standards/testing.md § T5` exists to prevent.
        Idempotent: `main` calls it, and so does every test fixture.

        `_stopped` is what closes INV-16, and it is checked in the slots rather
        than enforced by disconnecting here. Cutting the connections only
        helps while the emit has not yet happened: Qt dispatches a
        `QMetaCallEvent` that has already been **posted** regardless of any
        later disconnect, so a probe finishing just before `stop()` still
        delivered on the next spin (LWSM-1098). The earlier disconnect closed
        the window it was measured against and no other.
        """
        self._stopped = True
        self._timer.stop()
        # Otherwise a suppressed run's count dies with the process.
        self._flush_repeated_error()
        self._in_flight = False

        if not self._pool.waitForDone(STOP_WAIT_MS):
            # An unbounded wait here makes a probe that never returns into an
            # app that cannot be quit, which `§ 6` does not promise — it
            # promises only a stale display.
            log.warning(
                "a port probe was still running after %d ms; abandoning it so "
                "the app can quit",
                STOP_WAIT_MS,
            )
            self._pool.setParent(None)
            _ABANDONED.append(self._pool)
            self._pool = QThreadPool(self)
            self._pool.setMaxThreadCount(1)

    def close_supervisor(self) -> None:
        """Release the supervisor's descriptors and threads, if there is one.

        Separate from `stop()` because it is a different subject: `stop()` is
        about this controller's poll, and this is about children that
        deliberately **outlive** the window (ADR-0003). Idempotent.
        """
        if self._supervisor is not None:
            close = getattr(self._supervisor, "close", None)
            if close is not None:
                close()

    def poll_once(self) -> None:
        if self._stopped:
            # A stray tick after stop() would re-arm delivery into a controller
            # the app has already torn down (LWSM-1111).
            return
        if self._in_flight:
            # design.md § Data flow: "the poll skips a tick rather than
            # queueing". Queueing is how a briefly-slow socket table becomes a
            # permanently-lagging one.
            return
        self._in_flight = True
        self._pool.start(_SnapshotTask(self._probe, self._signals))

    def _on_snapshot(self, snapshot: PortSnapshot) -> None:
        if self._stopped:
            return
        self._in_flight = False
        # A success ends any suppressed run, so a failure that recurs after a
        # recovery is logged again rather than folded into the old count.
        self._flush_repeated_error()
        previous = self._statuses
        self._statuses = {
            record.path: self._classify(record, snapshot) for record in self._records
        }
        if self._settle_overlay():
            # Probing always wins, so a settled overlay is a visible change even
            # when the derived map happens to match the previous one.
            self.projects_changed.emit()
            return
        self._maybe_emit(previous)

    def _settle_overlay(self) -> bool:
        """Discard the overlay once a poll reports the state it was heading for.

        Not "once a poll returns": a server that has not finished binding reads
        as `stopped`, so clearing on any derived state would drop a `starting`
        overlay on the very next tick and the button would flicker straight
        back. There is no timeout here either — nothing may time out into a
        wrong state (ADR-0004 § Slowness is not failure).

        The overlay is also dropped when its project has left the list, which a
        rescan can do: an overlay keyed on a path nothing renders would sit
        there for the life of the session.
        """
        if self._overlay is None:
            return False
        path, pending = self._overlay
        if path not in self._statuses:
            self._overlay = None
            return True
        record = self._record(path)
        if record is not None and record.effective_port is None:
            # Nothing to wait for, so the overlay ends here (LWSM-1133).
            # `port is None` means *unknown, never a guess*, so `_classify`
            # returns UNKNOWN and neither of the two targets above is
            # reachable — the overlay could never settle and the row read
            # `starting` for the life of the session with every button dead.
            #
            # This is NOT a timeout, which ADR-0004 § Slowness is not failure
            # forbids: nothing is being waited out. The overlay covers the gap
            # between the button and the port appearing, and a project with no
            # port has no such gap — the honest answer, `unknown`, is already
            # available. So it settles on an observation like every other
            # case: the observation that there is nothing to observe.
            self._overlay = None
            return True
        if (
            pending is ProjectStatus.STARTING
            and self._supervisor is not None
            and self._supervisor.exited(path)
        ):
            # ADR-0004's own definition of `failed`: the child exited without
            # ever binding (LWSM-1134). The derived status stays `stopped`,
            # which is not `STARTING`'s target, so the overlay would sit there
            # for the life of the session. A project the supervisor no longer
            # holds a live child for cannot still be starting — and this is
            # terminal evidence rather than a timer, so ADR-0004 § Slowness is
            # not failure is untouched: a slow start still has a live child.
            self._overlay = None
            return True
        if self._statuses[path] == _OVERLAY_SETTLES_ON[pending]:
            self._overlay = None
            return True
        return False

    def _on_probe_error(self, exc: ProbeError) -> None:
        if self._stopped:
            return
        self._in_flight = False
        # An unreadable socket table is not evidence that anything stopped, so
        # every status keeps its previous value (INV-4b).
        #
        # Logged on the FIRST failure and then only when the message changes
        # (LWSM-1079). The poll is 1000 ms, so a permanently unreadable socket
        # table — a hardened kernel, a persistent AccessDenied — wrote roughly
        # 86,400 lines a day into a handler that rotates at 1 MiB keeping 5,
        # scrubbing away the history the user is told to consult. Suppressed by
        # message rather than by count, because a *different* failure is news.
        message = str(exc)
        if message == self._last_error:
            self._repeated_errors += 1
        else:
            self._flush_repeated_error()
            log.warning("port probe failed, holding previous statuses: %s", message)
            self._last_error = message
        self._maybe_emit(self._statuses)

    def _flush_repeated_error(self) -> None:
        """Report and clear the suppressed count, so silence and suppression
        are never indistinguishable in the log."""
        if self._repeated_errors:
            log.warning(
                "the previous port probe failure repeated %d more times",
                self._repeated_errors,
            )
        self._repeated_errors = 0
        self._last_error = None

    def _maybe_emit(self, previous: dict[Path, ProjectStatus]) -> None:
        # The first completed poll emits unconditionally. Deriving it from map
        # inequality would fail with zero records, where the map is empty
        # before and after and the empty window would never be rendered.
        if not self._emitted_once:
            self._emitted_once = True
            self.projects_changed.emit()
            return
        if previous != self._statuses:
            self.projects_changed.emit()

    @staticmethod
    def _classify(record: ProjectRecord, snapshot: PortSnapshot) -> ProjectStatus:
        port = record.effective_port
        if port is None:
            return ProjectStatus.UNKNOWN
        return (
            ProjectStatus.RUNNING if snapshot.is_bound(port) else ProjectStatus.STOPPED
        )
