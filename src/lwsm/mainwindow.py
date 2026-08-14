"""The window: one row per project, each stating its status as a word.

UI layer. Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`.

Two rules this file exists to obey. `docs/standards/coding.md § O7`: no colour
literal, no font family, no pixel constant — colours come from `Theme` tokens
and sizes from the text metric. `§ O8`: every row lands with an accessible
name, keyboard reachability, its state as text, and a layout that reflows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QRect,
    QRectF,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lwsm import applog, registry, scanner
from lwsm.controller import ProjectController, ProjectStatus, RowView
from lwsm.registry import LoadResult, MergeResult, ProjectRecord, RegistryError
from lwsm.theme import Theme

log = applog.get_logger(__name__)

# How long to wait for a rescan worker at teardown. The same bounded shape
# `controller.stop()` uses, and for the same reason: an unbounded wait turns a
# slow scan into an app that cannot be quit.
RESCAN_STOP_WAIT_MS = 5000

# Decorative only. One of the three signals design.md § Accessibility requires,
# and excluded from the accessible name — a screen reader announcing "black
# circle, running" is noise wearing the costume of redundancy.
STATE_GLYPHS = {
    ProjectStatus.RUNNING: "●",
    ProjectStatus.STOPPED: "○",
    ProjectStatus.UNKNOWN: "?",
    # The two overlay states. Distinct from each other and from the three
    # derived ones, because `design.md § Accessibility` asks for three
    # independent signals — word, colour and glyph — and a shared glyph would
    # quietly reduce that to two for exactly the states that change fastest.
    ProjectStatus.STARTING: "◌",
    ProjectStatus.STOPPING: "◑",
}


# Every user-visible string in this file goes through this context, so a future
# translator has one place to look (LWSM-1081, `coding.md § 5.2`). Deliberately
# NOT applied to log messages, which are read by whoever is debugging and want
# to match the source, nor to the argparse text in __main__ — translating that
# needs Qt imported before argparse runs, which INV-14 forbids.
_TR_CONTEXT = "ProjectRow"


def state_word(status: ProjectStatus) -> str:
    """The UI's word for a status.

    A display map rather than `str(status)`. The words come from a core
    `StrEnum`, so translating them by wrapping the enum would put user-visible
    UI text in a core module — this is the seam LWSM-1081 records rather than
    the wrapper it looked like it needed. An unmapped state falls back to its
    own value (LWSM-1082).
    """
    return {
        ProjectStatus.RUNNING: QCoreApplication.translate(_TR_CONTEXT, "running"),
        ProjectStatus.STOPPED: QCoreApplication.translate(_TR_CONTEXT, "stopped"),
        ProjectStatus.UNKNOWN: QCoreApplication.translate(_TR_CONTEXT, "unknown"),
        ProjectStatus.STARTING: QCoreApplication.translate(_TR_CONTEXT, "starting"),
        ProjectStatus.STOPPING: QCoreApplication.translate(_TR_CONTEXT, "stopping"),
    }.get(status, str(status))


def port_text(effective_port: int | None) -> str:
    """The word and the number, never a bare number.

    design.md § Accessibility gives the announcement as "…, port 5005"; a bare
    number leaves a listener with something unlabelled.
    """
    if effective_port is None:
        return QCoreApplication.translate(_TR_CONTEXT, "no port")
    # Qt's own %1 placeholder, substituted with str.replace rather than
    # str.format. A translation is data from outside the program: one that
    # dropped or misspelled a `{port}` field would raise KeyError or IndexError
    # here, inside a signal handler, which is the LWSM-1082 crash class
    # arriving by a new route. `replace` cannot raise whatever comes back — a
    # bad translation loses the number instead of taking the window down.
    return QCoreApplication.translate(_TR_CONTEXT, "port %1").replace(
        "%1", str(effective_port)
    )


def utc_stamp() -> str:
    """`added` in the one spelling LWSM-1131 § 4.3 pins.

    Not `datetime.now().isoformat()`: that is **naive**, the loader drops any
    `added` whose parsed `tzinfo` is `None`, and every record this app created
    would lose its timestamp on the next load — leaving the duplicate-port
    tie-break with nothing to compare on exactly the records the app made
    itself.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class RescanContext:
    """Everything a Rescan needs that the window does not already hold.

    `roots` is passed in rather than read from a settings file: settings
    persistence is LWSM-1018, and a window that read the real config could not
    satisfy `testing.md § T1`. `scan` and `now` are injected for the same
    reason — the tests supply fakes rather than walking a real tree.
    """

    projects_path: Path
    roots: tuple[Path, ...]
    scan: Callable[[Sequence[Path]], scanner.ScanResult] = scanner.scan
    now: Callable[[], str] = utc_stamp
    save: Callable[..., None] = field(default=registry.save_projects)


def summarise_merge(counts: dict[str, int]) -> str:
    """`MergeResult.counts` as one line, in a fixed order, omitting zeroes.

    Pinned because "a one-line summary" admits both `"Rescan complete"`, which
    satisfies no acceptance criterion, and `"; ".join(reasons)`, which is
    effectively unbounded — the report's cap bounds the entry *list*, not a line
    built by joining it.

    **`unchanged` is counted and never rendered** — it is the one outcome that
    is not news. The duplicate-port flag is likewise not rendered here: § 4.4's
    table has six rows and does not include it, and its entries still reach the
    application log with every other reason.
    """
    parts = [
        QCoreApplication.translate(_TR_CONTEXT, template).replace("%1", str(count))
        for outcome, template in (
            (registry.NEW, "%1 new"),
            (registry.CHANGED, "%1 changed"),
            (registry.NOT_REOBSERVED, "%1 port no longer detected"),
            (registry.OVERRIDE_DIFFERS, "%1 override differs"),
            (registry.DUPLICATE_IDENTITY, "%1 duplicate"),
            (registry.MISSING, "%1 missing"),
        )
        if (count := counts.get(outcome, 0))
    ]
    if not parts:
        return QCoreApplication.translate(_TR_CONTEXT, "Rescan: no changes")
    return QCoreApplication.translate(_TR_CONTEXT, "Rescan: %1").replace(
        "%1", ", ".join(parts)
    )


class _RescanSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _RescanTask(QRunnable):
    """Scan and merge on a pool thread; the write and the UI happen in the slot.

    `scan()` is budgeted precisely because it is slow — it walks roots, opens
    other people's files and may shell out to `systemctl` — so running it inline
    would freeze the window for its whole duration.

    The signaller belongs to the **window**, not to this task, for the reason
    `controller._SnapshotTask` records: owning one per task forces
    `setAutoDelete(False)` and nothing on the Python side can then free it.
    """

    def __init__(
        self,
        context: RescanContext,
        stored: list[ProjectRecord],
        signals: _RescanSignals,
    ) -> None:
        super().__init__()
        self._context = context
        self._stored = stored
        self.signals = signals

    def run(self) -> None:
        # Two layers, exactly as `_SnapshotTask` has: PySide6 **swallows** an
        # exception escaping run() — verified against the pinned 6.11.1 — the
        # process survives at exit 0 and *no signal is emitted*, so the in-flight
        # flag would stay set and Rescan would never re-enable. The outer layer
        # covers the case where the signaller itself is already gone.
        try:
            try:
                result = self._context.scan(self._context.roots)
                merged = registry.merge(
                    self._stored, result, self._context.roots, self._context.now
                )
            except BaseException as exc:
                log.exception("the rescan failed")
                self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            else:
                self.signals.done.emit(merged)
        except BaseException:
            log.debug("rescan ended with no live signaller", exc_info=True)


class ProjectRow(QFrame):
    """One project. Created once; `update_from` mutates it in place.

    Rebuilding the row on every signal would discard keyboard focus and
    re-announce every unchanged row — undoing at the widget level what the
    controller's change-detection achieves at the signal level.
    """

    def __init__(self, row: RowView, theme: Theme, parent: QWidget | None = None):
        super().__init__(parent)
        self._theme = theme
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QHBoxLayout(self)

        # The glyph is PAINTED, not labelled (LWSM-1071). It was a QLabel with
        # setAccessibleName(""), which does not hide anything: QAccessibleDisplay
        # falls back to QLabel::text() when the name is empty, so a screen reader
        # walking the row's children found a child named '●'. There is no
        # "ignored" flag for a QWidget, so the only way to keep something out of
        # the tree is for it not to be a widget.
        self._glyph_text = ""
        self._view: RowView | None = None
        # contentsMargins() -> QMargins, not getContentsMargins()'s tuple:
        # PySide6 types the latter as `object`, which a checker cannot unpack.
        margins = layout.contentsMargins()
        self._glyph_x = margins.left()
        # Kept because _apply_text_metrics re-derives the left margin from it on
        # every font change: adding the glyph column to whatever the margin
        # currently is would compound it on each call.
        self._base_margins = margins
        self._glyph_width = 0

        self._state = QLabel(self)
        self._name = QLabel(self)
        self._port = QLabel(self)
        for label in (self._state, self._name, self._port):
            # PlainText explicitly: Qt's default AutoText sniffs for rich text,
            # so a project named with markup would otherwise be rendered as it.
            label.setTextFormat(Qt.TextFormat.PlainText)

        # State cell first — design.md § Accessibility: "the state word is
        # first in the row". Visual order is tab order.
        layout.addWidget(self._state)
        layout.addWidget(self._name)
        layout.addWidget(self._port)
        # The buttons, after the cells so the state word is still first in tab
        # order (`design.md § Accessibility`). Created for every row and enabled
        # by status, rather than added and removed as the status changes:
        # rebuilding a row's controls would drop keyboard focus mid-transition,
        # which is exactly when a keyboard user is watching it.
        self.start_button = QPushButton(self)
        self.stop_button = QPushButton(self)
        self.restart_button = QPushButton(self)
        for button in (self.start_button, self.stop_button, self.restart_button):
            layout.addWidget(button)

        # Every pixel of slack goes here, after the last cell (LWSM-1074).
        # `stretch=1` on the name gave the slack to that label instead, and
        # QLabel aligns left by default — so the name's text stayed put while
        # the port was pinned to the right edge. Measured at 1400 px: name text
        # at x=84, port text at x=1333. design.md § Accessibility names that
        # exact shape ("never name on the far left and state on the far right,
        # which forces a pan and a memory test").
        layout.addStretch(1)

        self._apply_text_metrics()
        self.update_from(row)

    def _apply_text_metrics(self) -> None:
        """Sizes from the text metric, never a pixel constant (`§ O7`).

        Re-applied on every font change rather than computed once, so
        LWSM-1032's 100-200 % text-size control does not leave these stale.

        That was true only of a font set on *this widget* until LWSM-1119. An
        application-level change — the route a text-size control actually takes
        — delivered no `FontChange` here at all, because the window's style
        sheet makes Qt resolve a font onto every descendant and so marks it
        explicitly set. `MainWindow.changeEvent` now pushes the window font down
        to close that; the sentence above is accurate again, and was the third
        comment in this file found stating an intention as a fact (after
        LWSM-1071 and LWSM-1101).

        The **glyph column is one of them**, and until LWSM-1101 it was not:
        it and the widened left margin were computed once in `__init__` while
        this docstring already claimed otherwise. `paintEvent` clips the glyph
        to that column, so 13 px stayed reserved against 14 px needed at 200 %
        and 22 px at 300 % — a state indicator sliced in half at exactly the
        text size the users who depend on it are running.
        """
        metrics = self.fontMetrics()
        self._state.setMinimumWidth(metrics.horizontalAdvance("stopped_"))
        self._port.setMinimumWidth(metrics.horizontalAdvance("no port_"))

        layout = self.layout()
        self._glyph_width = metrics.horizontalAdvance("●") + layout.spacing()
        layout.setContentsMargins(
            self._base_margins.left() + self._glyph_width,
            self._base_margins.top(),
            self._base_margins.right(),
            self._base_margins.bottom(),
        )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._apply_text_metrics()

    def focus_ring_width(self) -> int:
        """Derived from the text metric, never a pixel constant (`§ O7`).

        A fixed width would thin to a hairline under LWSM-1032's 200 % text-size
        control, which is precisely the setting the users who depend on the ring
        are most likely to be running.
        """
        return max(1, round(self.fontMetrics().height() / 8))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the state glyph, and the focus ring `QFrame` does not.

        The glyph is painted rather than put in a `QLabel` so it stays out of
        the accessibility tree entirely (LWSM-1071).

        `QFrame` renders only its frame and `StyledPanel` never consults
        `State_HasFocus`, so before this the focused and unfocused renders were
        byte-identical and Tab moved an invisible caret (LWSM-1070).
        `coding.md § O8` requires a visible focus ring, `design.md
        § Accessibility` calls it the thing a magnifier user's "where am I?"
        depends on entirely, and WCAG 2.4.7 requires it outright.
        """
        super().paintEvent(event)

        glyph_painter = QPainter(self)
        glyph_painter.setPen(self._glyph_color)
        glyph_painter.drawText(
            QRect(self._glyph_x, 0, self._glyph_width, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
            self._glyph_text,
        )
        glyph_painter.end()

        if not self.hasFocus():
            return

        width = self.focus_ring_width()
        painter = QPainter(self)
        painter.setPen(QPen(self._theme.focus_ring_color(), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inset by half the pen, which straddles the path it is given: a
        # rectangle on the widget edge would lose its outer half to clipping and
        # render at half the width this method promises.
        inset = width / 2
        painter.drawRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset))

    def _apply_button_state(self, status: ProjectStatus) -> None:
        """Labels and enablement, both derived from the one status.

        **Both overlay states disable all three.** A second Stop while one is in
        flight would signal a group whose leader may already be reaped, and a
        Start during a stop is the race the pre-flight check exists to refuse —
        so the disable is correctness rather than politeness.

        `unknown` means nobody has looked yet, so Start is offered and Stop is
        not: starting something that turns out to be running is refused by the
        pre-flight check with a reason, while stopping something nobody has
        observed has nothing to signal.
        """
        self.start_button.setText(QCoreApplication.translate(_TR_CONTEXT, "Start"))
        self.stop_button.setText(QCoreApplication.translate(_TR_CONTEXT, "Stop"))
        self.restart_button.setText(QCoreApplication.translate(_TR_CONTEXT, "Restart"))
        in_transition = status in (ProjectStatus.STARTING, ProjectStatus.STOPPING)
        running = status is ProjectStatus.RUNNING
        self.start_button.setEnabled(not in_transition and not running)
        self.stop_button.setEnabled(not in_transition and running)
        self.restart_button.setEnabled(not in_transition and running)
        # An accessible name of its own on each, because the label alone reads
        # as "Start" three times over in a list of three projects (`§ O8`).
        for button, verb in (
            (self.start_button, "Start %1"),
            (self.stop_button, "Stop %1"),
            (self.restart_button, "Restart %1"),
        ):
            button.setAccessibleName(
                QCoreApplication.translate(_TR_CONTEXT, verb).replace(
                    "%1", self._name.text()
                )
            )

    def retranslate(self) -> None:
        """Re-render every cell from the `RowView` already held.

        `update_from` short-circuits on an unchanged view (LWSM-1076), which is
        right for a poll tick and wrong for a language change: the data did not
        change, the words for it did. Without this a translator installed
        *after* the window was built never reached an existing row, while a row
        built afterwards rendered translated — so § 4.4's stated reason for
        translating at call time was untrue as written (LWSM-1107).
        """
        view, self._view = self._view, None
        if view is not None:
            self.update_from(view)

    def update_from(self, row: RowView) -> None:
        if row == self._view:
            # `_sync_rows` calls this on EVERY row on every signal, and only
            # `QLabel::setText` short-circuits — `setStyleSheet` and
            # `setAccessibleName` do not, and the announcement below certainly
            # does not. Without this guard the announcement turns a
            # once-a-second no-op into a once-a-second re-announcement of every
            # unchanged row: the failure INV-13 exists to prevent, arriving by
            # another route. `RowView` is frozen, so the comparison is free.
            #
            # It also caches `_glyph_color`, and that is a live edge the moment
            # the palette can change: a theme swap with an unchanged RowView
            # would leave the glyph in the old palette while the *word* follows
            # the new one, because the word is restyled by the sheet and the
            # glyph is painted from this cached value. Unreachable in P02 — the
            # theme is built once — and LWSM-1031 is exactly when it becomes
            # reachable, so it is named here rather than guarded speculatively
            # (LWSM-1111). `retranslate()` is the shape the fix takes.
            return
        self._view = row

        # .get, not [...]: this runs inside a signal handler, so an unmapped
        # state would be a UI crash rather than a missing glyph — and LWSM-1011
        # adds four states. The word still carries the state either way.
        self._glyph_text = STATE_GLYPHS.get(row.status, "")
        self._glyph_color = self._theme.state_color(row.status)
        # The glyph is painted, so unlike the labels below it needs an explicit
        # repaint request — nothing else marks the row dirty.
        self.update()

        self._state.setText(state_word(row.status))
        self._name.setText(row.name)
        self._port.setText(port_text(row.effective_port))
        self._apply_button_state(row.status)

        # A property, not composed CSS: the rule lives in the theme's generated
        # style sheet (LWSM-1077). Qt does not re-evaluate a style-sheet selector
        # when the dynamic property it matches on changes, so the widget has to
        # be re-polished or it keeps the colour it was last polished with.
        #
        # Deleting these three lines was tried, on the strength of two tests
        # that stayed green without them — both were insensitive to it.
        # `test_the_state_word_takes_its_colour_from_the_status` is the one that
        # can see it, and it goes red immediately.
        self._state.setProperty(Theme.STATE_PROPERTY, row.status.value)
        style = self._state.style()
        style.unpolish(self._state)
        style.polish(self._state)

        # Built from the rendered cell strings, glyph excluded, so there is no
        # accessibility-only string that can drift from what is on screen.
        self.setAccessibleName(
            f"{self._state.text()}, {self._name.text()}, {self._port.text()}"
        )
        # Qt does NOT notify AT-SPI when an accessible name changes, so
        # `setAccessibleName` alone left `design.md § Accessibility`'s "a state
        # change announces itself once" unimplemented — a screen reader was
        # never told (LWSM-1076). Guarded by the equality check above, so this
        # fires once per real change and never on an unchanged tick.
        QAccessible.updateAccessibility(
            QAccessibleEvent(self, QAccessible.Event.NameChanged)
        )


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: ProjectController,
        theme: Theme,
        notices: list[str],
        parent: QWidget | None = None,
        *,
        rescan: RescanContext | None = None,
        load: LoadResult | RegistryError | None = None,
        confirm: Callable[[Path, str, tuple[str, ...]], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._theme = theme
        # Both optional so a window can still be built with nothing to rescan —
        # which is what every pre-LWSM-1131 test does, and what a session with
        # no scan roots configured would do. No context, no button: an enabled
        # control that cannot work is worse than an absent one.
        self._rescan = rescan
        self._load = load
        self._rescan_in_flight = False
        # Injected so the tests never open a real modal: a `QMessageBox.exec()`
        # in a test blocks the event loop with nothing to click it, which is a
        # hang rather than a failure.
        self._confirm = confirm if confirm is not None else self._confirm_dialog
        # QCoreApplication.translate under the file's one context, not
        # `self.tr(...)` — tr resolves under the *class*, so this string landed
        # in "MainWindow" (and Qt then walked QMainWindow, QWidget, QObject and
        # QPaintDevice looking for it) while every other string in this file is
        # in `_TR_CONTEXT`. § 4.4 asks for one place for a translator to look.
        self.setWindowTitle(self._window_title())
        # On the APPLICATION, not on `self`. `setStyleSheet` below installs
        # QStyleSheetStyle, and that re-resolves every descendant's palette from
        # the application palette — so a `self.setPalette(...)` themed the window
        # frame and nothing inside it. Verified on live widgets: `window` carried
        # WindowText=#1b1b1f while the central widget, the row and all three
        # cell labels carried Fusion's #000000. The light default hid it,
        # because Fusion's black is *darker* than the `text` token so contrast
        # was accidentally better; a dark theme rendered the name and port at
        # 1.25:1 and 1.27:1 against § T8's 4.5:1 floor (LWSM-1118).
        #
        # Application-wide is also the right scope rather than a workaround:
        # the theme governs P05's dialogs and P09's tray as much as this window,
        # and LWSM-1031's switcher will re-apply it here. The window inherits it
        # like every other widget, so the `self.setPalette` that used to sit here
        # became redundant and was removed with it — a line no test could redden
        # is the LWSM-1113 defect this pass exists to close.
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.to_palette())
        # Set once for the whole window; rows carry a state property the rules
        # in it select on.
        self.setStyleSheet(theme.style_sheet())

        central = QWidget(self)
        outer = QVBoxLayout(central)
        self._rescan_button: QPushButton | None = None
        self._rescan_pool: QThreadPool | None = None
        self._rescan_signals: _RescanSignals | None = None
        if self._rescan is not None:
            self._rescan_button = QPushButton(self._rescan_label(), central)
            # Visual order is tab order, and the button is a real QPushButton so
            # it is focusable and carries its own accessible name from its text
            # (`§ O8`).
            outer.addWidget(self._rescan_button)
            self._rescan_button.clicked.connect(self._start_rescan)
            # A private pool, not the global instance: teardown must wait for
            # this window's own worker and nothing else, which is
            # `ProjectController`'s reasoning on its poll.
            self._rescan_pool = QThreadPool(self)
            self._rescan_pool.setMaxThreadCount(1)
            self._rescan_signals = _RescanSignals(self)
            self._rescan_signals.done.connect(self._on_rescan_done)
            self._rescan_signals.failed.connect(self._on_rescan_failed)
        self._rows_layout = QVBoxLayout()
        outer.addLayout(self._rows_layout)
        self._rows_layout.addStretch(1)
        outer.addStretch(1)
        self.setCentralWidget(central)

        self._rows: dict[Path, ProjectRow] = {}
        self._sync_rows()
        controller.projects_changed.connect(self._sync_rows)
        controller.action_failed.connect(self.set_status_message)
        controller.confirmation_required.connect(self._ask_to_trust)

        if notices:
            self.set_status_message(self._notice_summary(notices))

    @staticmethod
    def _window_title() -> str:
        return QCoreApplication.translate(_TR_CONTEXT, "Local Web Server Manager")

    @staticmethod
    def _notice_summary(notices: list[str]) -> str:
        """The first notice, plus a count of the rest.

        The "(+N more)" half was an f-string and so never reached a translator,
        leaving it identical in every language against § 4.4's "**every**
        user-visible string in this file" (LWSM-1107). `%1` and `str.replace`
        for the same reason as `port_text`: a translation is data from outside
        the program and must not be able to raise in here.
        """
        first = notices[0]
        if len(notices) == 1:
            return first
        extra = QCoreApplication.translate(_TR_CONTEXT, " (+%1 more)").replace(
            "%1", str(len(notices) - 1)
        )
        return f"{first}{extra}"

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            # Qt sends LanguageChange to top-level widgets and does NOT
            # propagate it to children, so the rows are retranslated from here
            # — the same shape as a generated `retranslateUi`.
            #
            # The status bar is deliberately not re-derived: `build_window`
            # may have replaced the notice summary with a RegistryError, and
            # re-applying the summary here would silently overwrite it.
            self.setWindowTitle(self._window_title())
            for row in self._rows.values():
                row.retranslate()
        elif event.type() == QEvent.Type.FontChange:
            # Same shape, same reason, and a second consequence of the style
            # sheet. QStyleSheetStyle resolves a font onto every descendant,
            # which marks it explicitly set — so an application font change
            # reaches this window and stops, delivering no `FontChange` to a row
            # and not updating its font either. Measured 2026-08-07:
            # `QApplication.setFont()` and `MainWindow.setFont()` each produced
            # **zero** calls to `ProjectRow._apply_text_metrics`, against 1 for
            # `row.setFont()`. Isolated against a bare QWidget tree, the same
            # change delivers 1 `FontChange` with no style sheet and 0 with one.
            #
            # That made `§ O8` clause 4's 100-200 % text-size path dead by the
            # only route a real control takes, while three tests reported it
            # covered because all three called `row.setFont` (LWSM-1119).
            #
            # Pushing `self.font()` rather than `QApplication.font()` so
            # `MainWindow.setFont()` works too — both raise this event here.
            for row in self._rows.values():
                row.setFont(self.font())

    def set_status_message(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _confirm_dialog(
        self, project: Path, resolved: str, argv: tuple[str, ...]
    ) -> bool:
        """ADR-0003 § Trust, on screen.

        It shows the **resolved absolute path and the exact argv**, never a
        friendly summary: "the confirmation is not security theatre only if it
        shows what will actually run". `Qt.PlainText` explicitly, because the
        thing being displayed is a path from a directory anybody could have
        written into, and Qt's default sniffs for rich text.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(
            QCoreApplication.translate(_TR_CONTEXT, "Run this launcher?")
        )
        box.setText(
            QCoreApplication.translate(
                _TR_CONTEXT,
                "%1 has not been run from here before.\n\n"
                "This will execute:\n%2\n\nwith arguments:\n%3",
            )
            .replace("%1", project.name)
            .replace("%2", resolved)
            .replace("%3", " ".join(argv))
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        # No by default: a confirmation whose default is yes is a confirmation
        # that gets dismissed rather than read.
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _ask_to_trust(self, project: Path, refusal: object) -> None:
        resolved = getattr(refusal, "resolved", None)
        argv = getattr(refusal, "argv", ())
        fingerprint = getattr(refusal, "fingerprint", "")
        if self._confirm(project, str(resolved or argv[0] if argv else ""), argv):
            self._controller.confirm_and_start(project, fingerprint)
        else:
            self.set_status_message(
                QCoreApplication.translate(_TR_CONTEXT, "%1 was not started").replace(
                    "%1", project.name
                )
            )

    @staticmethod
    def _rescan_label() -> str:
        return QCoreApplication.translate(_TR_CONTEXT, "Rescan")

    def shutdown(self) -> None:
        """Wait, bounded, for a rescan worker. Idempotent.

        Called beside `controller.stop()`. Without it a pool thread finishes
        into a window being torn down, which is the flake `testing.md § T5`
        exists to prevent — and `~QThreadPool` joins with **no** timeout, so the
        cost of not doing it is invisible to pytest's own number and shows up
        only as process wall time.
        """
        self._rescan_in_flight = False
        if self._rescan_pool is not None and not self._rescan_pool.waitForDone(
            RESCAN_STOP_WAIT_MS
        ):
            log.warning(
                "a rescan was still running after %d ms; abandoning it so the "
                "app can quit",
                RESCAN_STOP_WAIT_MS,
            )

    def _start_rescan(self) -> None:
        """One at a time: two overlapping merges could both write."""
        # The three are created together or not at all, so testing the pool
        # covers the set. `assert` would be the natural narrowing here and is
        # forbidden by `S101`: an assertion is removed under `python -O`, and
        # this one guards a `None` dereference in a slot.
        if (
            self._rescan is None
            or self._rescan_in_flight
            or self._rescan_pool is None
            or self._rescan_signals is None
        ):
            return
        self._rescan_in_flight = True
        if self._rescan_button is not None:
            self._rescan_button.setEnabled(False)
        self._rescan_pool.start(
            _RescanTask(self._rescan, self._controller.records(), self._rescan_signals)
        )

    def _finish_rescan(self, message: str) -> None:
        self._rescan_in_flight = False
        if self._rescan_button is not None:
            self._rescan_button.setEnabled(True)
        self.set_status_message(message)

    def _on_rescan_failed(self, detail: str) -> None:
        log.warning("rescan failed: %s", detail)
        self._finish_rescan(
            QCoreApplication.translate(_TR_CONTEXT, "Rescan failed: %1").replace(
                "%1", detail
            )
        )

    def _on_rescan_done(self, merged: MergeResult) -> None:
        """The write and every UI update, on the GUI thread.

        The write gate is LWSM-1007's and it stays there: `merge()` is handed no
        `LoadResult` and calls no writer, because it runs on the pool thread.
        The load this window started from is the only thing that knows whether
        the session may write, and this slot is the only place both values are
        in scope.
        """
        if self._rescan is None:
            return
        for reason in merged.reasons:
            # The full report goes to the log, one record each; the status bar
            # gets the summary. INV-6's bound already applies to the entries.
            log.info("rescan: %s", reason)

        stored = self._controller.records()
        message = summarise_merge(merged.counts)
        if self._should_write(merged, stored):
            try:
                self._rescan.save(
                    self._rescan.projects_path, merged.records, load=self._load
                )
            except RegistryError as exc:
                log.warning("the rescan could not be saved: %s", exc)
                message = (
                    QCoreApplication.translate(_TR_CONTEXT, "%1 — not saved: %2")
                    .replace("%1", message)
                    .replace("%2", str(exc))
                )
            else:
                # The next rescan compares against what is now on disk. Without
                # this, a first run stays `RegistryMissing` for the life of the
                # session and every later rescan writes unconditionally.
                self._load = LoadResult(
                    records=list(merged.records), reasons=[], rows_refused=0
                )

        self._controller.set_records(merged.records)
        self._finish_rescan(message)

    def _should_write(self, merged: MergeResult, stored: list[ProjectRecord]) -> bool:
        """Exactly one trigger, plus first run.

        Record **content**, not report entries: three outcomes flag a row while
        leaving every field identical — *missing*, *not re-observed* and
        *duplicate identity* — and none of them writes. A no-op rewrite would
        churn the file's mtime and widen the only window in which a concurrent
        writer can lose an edit, for no gain.

        First run is the exception and is not an optimisation: with no file,
        "differs from the loaded one" is vacuous, and on a clean machine whose
        first scan finds **zero** projects both sets are empty, the difference
        test says no, and `projects.json` would never come into existence at
        all — every later run repeating the whole first-run path.
        """
        if isinstance(self._load, registry.RegistryMissing):
            return True
        return merged.records != stored

    def _sync_rows(self) -> None:
        views = self._controller.rows()
        for view in views:
            existing = self._rows.get(view.path)
            if existing is None:
                widget = ProjectRow(view, self._theme, self)
                # Bound with a default argument rather than a closure over
                # `view`: the loop variable is rebound on every iteration, so a
                # plain closure would leave every row's buttons driving the last
                # project in the list.
                path = view.path
                widget.start_button.clicked.connect(
                    lambda _checked=False, p=path: self._controller.start_project(p)
                )
                widget.stop_button.clicked.connect(
                    lambda _checked=False, p=path: self._controller.stop_project(p)
                )
                widget.restart_button.clicked.connect(
                    lambda _checked=False, p=path: self._controller.restart_project(p)
                )
                self._rows[view.path] = widget
                # Before the trailing stretch, so rows stay top-aligned.
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, widget)
            else:
                existing.update_from(view)

        # Rows are also REMOVED. Without this a project dropped from the list
        # lingers showing its last observed state, which `§ O5` forbids —
        # harmless in P02 where the list cannot change, but the signal is
        # already called projects_changed and LWSM-1008 will change it.
        live = {view.path for view in views}
        for path in [known for known in self._rows if known not in live]:
            widget = self._rows.pop(path)
            # setParent(None), not removeWidget: removeWidget takes the widget
            # out of the LAYOUT and neither hides nor reparents it, so the row
            # stayed visible, stayed a child of the central widget, and kept
            # its rectangle — which the surviving row then moved into, leaving
            # the two overlapping. `deleteLater` only lands on a DeferredDelete
            # pass, so the object is still valid and still painted until then.
            # Sub-frame in production; an undocumented dependence on Qt's
            # delete ordering all the same (LWSM-1106).
            widget.setParent(None)
            widget.deleteLater()
