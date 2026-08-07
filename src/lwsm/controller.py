"""The one object the UI talks to: polls the socket table, holds the statuses.

Core module — QtCore only, never QtWidgets (`docs/standards/coding.md § O1`),
so the whole poll loop is testable without a display. Contract:
`docs/specs/LWSM-1005-vertical-slice.md § 4.3`.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from lwsm.ports import PortSnapshot, ProbeError, SupportsSnapshot
from lwsm.registry import ProjectRecord

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


class ProjectController(QObject):
    projects_changed = Signal()

    def __init__(
        self,
        records: list[ProjectRecord],
        probe: SupportsSnapshot,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._records = records
        self._probe = probe
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
                status=self._statuses[record.path],
            )
            for record in self._records
        ]

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
        self._maybe_emit(previous)

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
