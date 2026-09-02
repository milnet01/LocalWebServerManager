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
from lwsm.settings import DEFAULT_POLL_INTERVAL_MS
from lwsm.supervisor import (
    LauncherUntrusted,
    ManagedProcess,
    StopOutcome,
    SupervisorError,
)

log = logging.getLogger(__name__)

# An alias, not a second constant: `settings.py` owns the value so the file's
# default and the code's default cannot drift (LWSM-1018). The name stays
# because two test modules import it, and because "the interval a controller
# polls at" is what a reader of this module is looking for.
POLL_INTERVAL_MS = DEFAULT_POLL_INTERVAL_MS

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


def abandon_pool(pool: QThreadPool) -> None:
    """Give up on a pool whose worker will not finish, without destroying it.

    `~QThreadPool` calls `waitForDone()` with NO timeout, so simply dropping the
    reference reintroduces exactly the hang the caller's budget just declined to
    take. Reparenting to nothing and holding it in `_ABANDONED` defers the
    destructor to interpreter shutdown, where
    `exit_without_waiting_for_abandoned_probes` is the half that actually bounds
    it.

    Public because the window's rescan worker is a second pool with the same
    hazard (LWSM-1139), and a second hand-written copy of this two-line dance is
    what `coding.md § 1.3` forbids — one that forgot the `setParent(None)` would
    look identical and hang on exit.
    """
    pool.setParent(None)
    _ABANDONED.append(pool)


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

    def owns_pid(self, project: Path, pid: int) -> bool: ...

    def exited(self, project: Path) -> bool: ...

    def is_stopping(self, project: Path) -> bool: ...

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
    # Whether THIS manager spawned the process holding the port. `status` cannot
    # answer it: ADR-0004 classifies from the socket table, so a server someone
    # else started reads `running` exactly like one of ours. Open-in-browser is
    # gated on it (LWSM-1141).
    managed: bool = False
    # Whether a stop is in flight for this project. Start is gated on it
    # (LWSM-1191): the supervisor refuses a Start issued inside that window, so
    # offering one produces an error from a control that looked available.
    # `status` cannot answer this — a stopping project's entry is popped before
    # the sequence begins, and where its port is unknown the overlay is dropped
    # on the very next poll.
    stopping: bool = False
    # The user's own "do not show me this" flag, stored since LWSM-1007 and
    # read by nothing until LWSM-1185. Carried on the view rather than looked
    # up by the window, so the row has one source for everything it renders.
    hidden: bool = False
    # The desktop entry id of the browser this project's Open uses, or None for
    # the desktop default (LWSM-1187). Carried here for `hidden`'s reason: the
    # row renders it, so the row's one source should hold it. The id is not
    # resolved to a `Browser` here — that needs `browsers.py`'s scan of the
    # desktop, which is the window's to do once rather than the controller's to
    # repeat every poll.
    browser: str | None = None


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
    # (path, message). The PATH is what lets the window put the message beside
    # the row that raised it rather than in a corner — `design.md
    # § Accessibility`: "a message in a far-off status bar is invisible to
    # someone whose lens is on a button" (LWSM-1032). Carried on the signal
    # rather than recovered from the text, which would be string-matching a
    # project name back out of a sentence.
    action_failed = Signal(object, str)
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
        # Recomputed from each snapshot by `_managed_paths`. Empty until the
        # first poll completes, which is the honest answer: nothing has looked
        # at the socket table yet, so nothing is known to be ours.
        self._managed: set[Path] = set()
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
        managed = self._managed
        supervisor = self._supervisor
        return [
            RowView(
                path=record.path,
                name=record.name,
                effective_port=record.effective_port,
                status=self._status_of(record.path),
                managed=record.path in managed,
                # Asked at render time, unlike `managed`. That one has to come
                # from the poll's own snapshot (LWSM-1167) because it is a fact
                # about the socket table; this is the supervisor's own
                # bookkeeping, and the only useful answer is the current one.
                stopping=supervisor is not None and supervisor.is_stopping(record.path),
                hidden=record.hidden,
                browser=record.browser,
            )
            for record in self._records
        ]

    def _spawning_paths(self) -> set[Path]:
        """The projects we hold a live child for.

        ADR-0004's `starting` row is "live child, effective port held by
        nobody, child holds no port", so this is the half of it the socket
        table cannot answer. It exists because the optimistic overlay is ONE
        slot — `design.md § State management` says so deliberately — and
        starting a second project therefore takes the first one's label away
        while its child is still binding. With nothing derived underneath, the
        first project fell back to `stopped` and offered a Start that could
        only be refused (LWSM-1202).

        A second overlay slot would have fixed the symptom by contradicting
        that contract. This is the state the ADR already asks to be derived.

        `exited()` rather than `running()` alone: an entry survives the child
        that died, and a project whose child is gone is not starting.
        """
        if self._supervisor is None:
            return set()
        live = self._supervisor.running()
        return {path for path in live if not self._supervisor.exited(path)}

    def _managed_paths(self, snapshot: PortSnapshot) -> set[Path]:
        """The projects whose EFFECTIVE PORT is held by our own child's group.

        **Not `set(supervisor.running())`, which was the whole defect.** That
        says we hold an ENTRY for the project -- never who holds the port, and
        since LWSM-1165 not even that our child is the one listening. ADR-0004
        defines `running (managed)` as "effective port held by that child's
        group", and Open-in-browser is gated on it, so a stranger sitting on the
        registered port used to enable Open with this app's credibility behind
        it. Reproduced end to end 2026-08-24 (LWSM-1167).

        Identity is the recorded child PID plus its `create_time`, never the
        holder's working directory: ADR-0004 says the "looks like this project"
        test "is a display heuristic with no security value, and nothing may be
        gated on it", because `chdir()` is free. `owns_pid` carries both halves.

        A port whose holder the kernel will not name -- another user's, without
        root -- yields `None` here and is therefore not ours. That is the safe
        direction and it is the reason `holders` is allowed to be partial.
        """
        if self._supervisor is None:
            return set()
        managed: set[Path] = set()
        for record in self._records:
            port = record.effective_port
            if port is None:
                continue
            holder = snapshot.holder(port)
            if holder is not None and self._supervisor.owns_pid(record.path, holder):
                managed.add(record.path)
        return managed

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
            self.action_failed.emit(
                path, f"cannot start {path}: nothing to start it with"
            )
            return
        if not record.argv:
            # An honest refusal rather than a guess. The launcher is a detected
            # field, so the answer is a rescan, and saying so is more use than
            # "failed to start".
            self.action_failed.emit(
                path, f"{record.name} has no launcher recorded — run Rescan first"
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
            self.action_failed.emit(path, f"{record.name}: {exc}")
            return
        except OSError as exc:
            # The log file could not be opened. Distinct from SupervisorError
            # because it is about this machine rather than about the project.
            self.action_failed.emit(path, f"{record.name}: {exc}")
            return
        self._set_overlay(path, ProjectStatus.STARTING)

    def stop_project(self, path: Path) -> None:
        """Signal the group, and show `stopping` immediately.

        The stop itself runs on a worker: a five-second grace period on the UI
        thread would freeze the window (ADR-0003).
        """
        record = self._record(path)
        if record is None or self._supervisor is None:
            self.action_failed.emit(
                path, f"cannot stop {path}: nothing is supervising it"
            )
            return
        if path not in self._supervisor.running():
            # A `running (foreign)` project — this manager did not spawn it, so
            # it has no handle to signal through, and ADR-0003 forbids
            # signalling a bare PID. The foreign-stop path is a separate item.
            self.action_failed.emit(
                path,
                f"{record.name} was not started by this manager, so it cannot "
                "be stopped from here yet",
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
        """Handle the outcome, then re-render whatever the answer was.

        The emit is unconditional and in a `finally` because the supervisor's
        stop reservation — which `RowView.stopping` reads and Start is gated on
        (LWSM-1191) — is released before the future resolves, and nothing else
        observes it: `_maybe_emit` compares statuses only, and a port-less
        project's status never changes. Without this the Start button would
        stay disabled until some unrelated change re-rendered the row, which is
        LWSM-1133's defect reached by another route. Measured: the test for the
        gate timed out waiting for this signal.
        """
        if self._stopped:
            return
        try:
            self._apply_stop_outcome(path, outcome)
        finally:
            self.projects_changed.emit()

    def _apply_stop_outcome(self, path: Path, outcome: object) -> None:
        pending_restart = path in self._restarting
        self._restarting.discard(path)
        if isinstance(outcome, BaseException):
            self._clear_overlay(path)
            self.action_failed.emit(path, f"could not stop {path.name}: {outcome}")
            return
        if isinstance(outcome, StopOutcome):
            if outcome.warning:
                # A bound port after a stop is a warning, never a second signal.
                self.action_failed.emit(path, outcome.warning)
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

    def set_poll_interval_ms(self, interval_ms: int) -> None:
        """Change the poll cadence, taking effect without a restart (LWSM-1018).

        `QTimer.setInterval` is honoured on a running timer, so there is no
        stop/start dance and no lost tick. It is deliberately NOT clamped here:
        `settings._bounded_int_or_reason` refuses a value outside the range
        before it is ever stored, and a second, silent clamp at the point of
        use would turn a rejected setting into one that appears to work.
        """
        self._timer.setInterval(interval_ms)

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
            abandon_pool(self._pool)
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
        # Both before the in-flight guard, not after it: neither is a probe,
        # and a bound that lapses whenever the socket table is slow is weaker
        # than the one design.md promises (LWSM-1136).
        #
        # Reaping first so a log about to be released is not rotated on the way
        # out.
        self._reap_exited()
        self._rotate_logs()
        if self._in_flight:
            # design.md § Data flow: "the poll skips a tick rather than
            # queueing". Queueing is how a briefly-slow socket table becomes a
            # permanently-lagging one.
            return
        self._in_flight = True
        self._pool.start(_SnapshotTask(self._probe, self._signals))

    def _reap_exited(self) -> None:
        """Release the slot of any project whose group has gone (LWSM-1165).

        Only `start()` inserted and only `stop()` popped, so a launcher that
        died by itself kept its slot for the session: Stop and Restart greyed
        out because the port was free, and every Start raising `AlreadyRunning`
        with no route back. `Supervisor.reap_exited` decides *what* is safe to
        release — a launcher that forked and exited is not, since `stop()`
        signals the group through that entry — and this is the caller that
        makes it happen, which is the half LWSM-1136 shipped without.

        The poll is where it belongs for `_rotate_logs`' reason: it is the one
        thing already running once a second, and the cost on an ordinary tick
        is one `/proc` read per running project.

        Reached through `getattr` and contained, both for `_rotate_logs`'
        reasons — a supervision fake need not have the method, and this runs in
        a timer slot on the GUI thread where an escaping exception is swallowed
        by PySide6, taking the tick's probe with it.
        """
        supervisor = self._supervisor
        if supervisor is None:
            return
        reap = getattr(supervisor, "reap_exited", None)
        if reap is None:
            return
        try:
            reap()
        except Exception:
            log.warning("could not release exited projects", exc_info=True)

    def _rotate_logs(self) -> None:
        """Hold every managed log to `MAX_LOG_BYTES`, once a tick.

        `design.md § Observability` promises each project's log is capped with
        one rotation and `Supervisor.rotate_if_needed` implements it — but until
        LWSM-1136 nothing outside a test called it, so a chatty or looping
        server appended to an `O_APPEND` descriptor with no bound at all until
        the disk filled. A method with no caller is not a cap.

        The poll is where the call belongs: it is the one thing already running
        once a second holding the running set. Cost on an ordinary tick is one
        `fstat` per running project; the copy happens only on the tick that
        crosses the cap, so the overshoot is bounded by one poll interval of
        output rather than being unbounded.

        Reached through `getattr` for `close_supervisor`'s reason rather than by
        widening `SupportsSupervision`: a fake with no logs has nothing to
        rotate, and requiring the method would rewrite every supervision fixture
        in the suite to no purpose.
        """
        supervisor = self._supervisor
        if supervisor is None:
            return
        rotate = getattr(supervisor, "rotate_if_needed", None)
        if rotate is None:
            return
        for path in supervisor.running():
            try:
                rotate(path)
            except Exception:
                # Contained per project, and as wide as INV-4c's clause for the
                # same reason: this runs in a timer slot on the GUI thread, so
                # anything escaping it is swallowed by PySide6 — no crash, no
                # dialog, and one unreadable log would silently stop every other
                # project's being capped.
                log.warning("could not rotate the log for %s", path, exc_info=True)

    def _on_snapshot(self, snapshot: PortSnapshot) -> None:
        if self._stopped:
            return
        self._in_flight = False
        # A success ends any suppressed run, so a failure that recurs after a
        # recovery is logged again rather than folded into the old count.
        self._flush_repeated_error()
        previous = self._statuses
        spawning = self._spawning_paths()
        self._statuses = {
            record.path: self._classify(record, snapshot, record.path in spawning)
            for record in self._records
        }
        # Derived from the SAME snapshot as the statuses, in the same tick.
        # Asking the supervisor separately at render time is what LWSM-1167 was
        # -- the answer has to come from the socket table, and this is the only
        # scope that holds one.
        self._managed = self._managed_paths(snapshot)
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
    def _classify(
        record: ProjectRecord, snapshot: PortSnapshot, spawning: bool = False
    ) -> ProjectStatus:
        """`running` if EITHER port is held, `stopped` only if neither is.

        ADR-0004: "a project's `declared` port is probed as well as its
        effective one, whenever the two differ". `effective_port` is the
        override once one is set, so the declared port went unlooked-at and a
        project that ignored its override read as `stopped` while its server
        was up — and the ADR names the consequence, that "Start would
        cheerfully spawn a duplicate" (LWSM-1201).

        Both ports come from the same snapshot, so the second question costs
        nothing.

        Reported as plain `running`. Which of the two ports is held is the
        difference between `running (managed)` and `running (wrong port)`,
        and those are two of the four states P06's model adds; drawing that
        distinction here would be that item rather than this one. What this
        owes today is not calling a live project stopped.
        """
        port = record.effective_port
        if port is None:
            return ProjectStatus.UNKNOWN
        if snapshot.is_bound(port):
            return ProjectStatus.RUNNING
        declared = record.port
        if declared is not None and declared != port and snapshot.is_bound(declared):
            return ProjectStatus.RUNNING
        # Nobody holds either port. ADR-0004's `starting` row is exactly that
        # plus a live child of ours, and it reads AFTER the two port questions
        # for the ADR's own reason: a child that is live while someone else
        # holds the port is `failed` or `running (wrong port)`, never
        # `starting`. Both of those are P06 states, and both are reported as
        # `running` above rather than falling through to here (LWSM-1202).
        #
        # No deadline, so ADR-0004 § Slowness is not failure is untouched: a
        # slow start keeps a live child, and losing the child is what ends it.
        if spawning:
            return ProjectStatus.STARTING
        return ProjectStatus.STOPPED
