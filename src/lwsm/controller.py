"""The one object the UI talks to: polls the socket table, holds the statuses.

Core module — QtCore only, never QtWidgets (`docs/standards/coding.md § O1`),
so the whole poll loop is testable without a display. Contract:
`docs/specs/LWSM-1005-vertical-slice.md § 4.3`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from lwsm.ports import PortSnapshot, ProbeError, SupportsSnapshot
from lwsm.registry import ProjectRecord

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 1000


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
    """

    def __init__(self, probe: SupportsSnapshot) -> None:
        super().__init__()
        self._probe = probe
        self.signals = _SnapshotSignals()
        # The pool would otherwise free us while a queued emission is in flight.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            snapshot = self._probe.snapshot()
        except ProbeError as exc:
            self.signals.failed.emit(exc)
        except BaseException as exc:
            # An exception escaping run() is swallowed by PySide6 (verified
            # against the pinned 6.11.1, LWSM-1069): the traceback prints to
            # stderr, the process survives at exit 0, and *no* signal is
            # emitted — so the controller's in-flight guard is never cleared and
            # poll_once returns early on every later tick for the life of the
            # process. The window then shows plausible, permanently frozen data.
            # Nothing may leave this method, so the clause is as wide as the
            # language allows rather than as wide as the failures we predicted.
            log.exception("the port probe raised an unexpected exception")
            failure = ProbeError(f"the port probe failed: {type(exc).__name__}: {exc}")
            failure.__cause__ = exc
            self.signals.failed.emit(failure)
        else:
            self.signals.done.emit(snapshot)


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
        self._task: _SnapshotTask | None = None
        self._emitted_once = False

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
        """Timer off, then wait for any outstanding task.

        Without the wait a pool thread emits into a controller being torn
        down — the flake `docs/standards/testing.md § T5` exists to prevent.
        """
        self._timer.stop()
        QThreadPool.globalInstance().waitForDone()
        self._task = None

    def poll_once(self) -> None:
        if self._task is not None:
            # design.md § Data flow: "the poll skips a tick rather than
            # queueing". Queueing is how a briefly-slow socket table becomes a
            # permanently-lagging one.
            return
        task = _SnapshotTask(self._probe)
        # Connected on the owning thread before submission, so both are queued.
        task.signals.done.connect(self._on_snapshot)
        task.signals.failed.connect(self._on_probe_error)
        self._task = task
        QThreadPool.globalInstance().start(task)

    def _on_snapshot(self, snapshot: PortSnapshot) -> None:
        self._task = None
        previous = self._statuses
        self._statuses = {
            record.path: self._classify(record, snapshot) for record in self._records
        }
        self._maybe_emit(previous)

    def _on_probe_error(self, exc: ProbeError) -> None:
        self._task = None
        # An unreadable socket table is not evidence that anything stopped, so
        # every status keeps its previous value (INV-4b).
        log.warning("port probe failed, holding previous statuses: %s", exc)
        self._maybe_emit(self._statuses)

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
