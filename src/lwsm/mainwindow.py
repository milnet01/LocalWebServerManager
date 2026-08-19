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
    QPoint,
    QRect,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QAction,
    QActionGroup,
    QDesktopServices,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lwsm import applog, registry, scanner
from lwsm.controller import (
    ProjectController,
    ProjectStatus,
    RowView,
    abandon_pool,
)
from lwsm.registry import LoadResult, MergeResult, ProjectRecord, RegistryError
from lwsm.settings import MAX_TEXT_SCALE, MIN_TEXT_SCALE
from lwsm.theme import THEMES, Theme, theme_for_id

log = applog.get_logger(__name__)

# How long to wait for a rescan worker at teardown. The same bounded shape
# `controller.stop()` uses, and for the same reason: an unbounded wait turns a
# slow scan into an app that cannot be quit.
RESCAN_STOP_WAIT_MS = 5000

# How many rows the window shows before the list starts scrolling, and the
# fewest it stays legible at (LWSM-1149). Counts of rows, not pixels: the
# height each implies is measured off a real row at the current text size.
TEXT_SIZE_STEPS = (MIN_TEXT_SCALE, 125, 150, 175, MAX_TEXT_SCALE)
"""The steps the text-size control offers, as percentages (LWSM-1032).

The two ends are `settings.MIN/MAX_TEXT_SCALE` rather than literals, so the
menu cannot come to offer a size the settings file would refuse to store.
"""

DEFAULT_VISIBLE_ROWS = 8
MIN_VISIBLE_ROWS = 3

# Decorative only. One of the three signals design.md § Accessibility requires,
# and excluded from the accessible name — a screen reader announcing "black
# circle, running" is noise wearing the costume of redundancy.
MIN_TARGET_PX = 24
"""`design.md § Accessibility`: no clickable target smaller than 24x24 at
100 %. A FLOOR, not a size — everything here is derived from the text metric
and grows with the text-size control (`§ O7`)."""

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


def project_url(port: int) -> QUrl:
    """`http://localhost:<port>/`, built rather than concatenated.

    `QUrl.setPort` with an integer rather than an f-string, following the rule
    `design.md § Custom project actions` states for user-authored URLs —
    substituting a value into a string before parsing is how
    `http://localhost:0@evil.example/` gets made.

    **On this call site that is consistency, not a hole being closed, and the
    mutation says so:** `port` here is an `int` validated by the registry's
    1-65535 range, so `QUrl(f"http://localhost:{port}/")` produces the identical
    URL and the mutant survives every test. Recorded rather than dressed up as a
    security fix — the live version of this rule is LWSM-1121's `open_url`
    action, where the value is user-authored text.

    **The port is the one observed BOUND, not the one requested.** The two
    differ exactly when a project ignored `PORT`, which is the case this button
    would otherwise get wrong every time — and the status is derived from the
    socket table, so a row reading `running` is a row whose port is bound.
    """
    url = QUrl()
    url.setScheme("http")
    url.setHost("localhost")
    url.setPort(port)
    url.setPath("/")
    return url


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

        # Two layouts, not one: the cells and controls across, and the failure
        # message under them (LWSM-1032). A message beside the controls would
        # be horizontal sprawl, which `design.md § Accessibility` rules out in
        # the same breath as it asks for the message to be here at all —
        # "vertical rhythm stays generous, horizontal sprawl does not".
        #
        # The outer layout keeps the widget's default margins so `_glyph_x` is
        # unchanged; the inner one carries the glyph column and no margins of
        # its own, or the two would add up.
        outer = QVBoxLayout(self)
        layout = QHBoxLayout()
        outer.addLayout(layout)

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
        margins = outer.contentsMargins()
        self._glyph_x = margins.left()
        outer.setContentsMargins(0, margins.top(), 0, margins.bottom())
        self._cells_layout = layout
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
        self.open_button = QPushButton(self)
        for button in (
            self.start_button,
            self.stop_button,
            self.restart_button,
            self.open_button,
        ):
            layout.addWidget(button)

        # Every pixel of slack goes here, after the last cell (LWSM-1074).
        # `stretch=1` on the name gave the slack to that label instead, and
        # QLabel aligns left by default — so the name's text stayed put while
        # the port was pinned to the right edge. Measured at 1400 px: name text
        # at x=84, port text at x=1333. design.md § Accessibility names that
        # exact shape ("never name on the far left and state on the far right,
        # which forces a pan and a memory test").
        layout.addStretch(1)

        # Created only when something fails, never kept hidden. A hidden
        # QLabel is still a child of the accessibility tree — measured: it
        # reports `invisible` but it is there, named `''` — and an unnamed
        # child is what LWSM-1071 spent an item removing. It also must not
        # reserve height while empty: a blank line under every row is the
        # horizontal-sprawl problem turned vertical, on a list read one row at
        # a time.
        self._error: QLabel | None = None
        self._outer_layout = outer

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
        # Held as attributes as well as pushed into the widgets: once
        # `apply_column_widths` has set a shared width, `minimumWidth()` reports
        # that width rather than this floor, so re-reading it to compute the
        # next natural width would make the column monotonic — it would grow
        # when a long-named project appeared and never shrink when it left
        # (LWSM-1145).
        self._state_floor = metrics.horizontalAdvance("stopped_")
        self._port_floor = metrics.horizontalAdvance("no port_")
        self._state.setMinimumWidth(self._state_floor)
        self._port.setMinimumWidth(self._port_floor)

        # The INNER layout: `self.layout()` is the vertical one that holds it
        # and the failure line, and widening its left margin would indent the
        # message as well as the cells.
        layout = self._cells_layout
        self._glyph_width = metrics.horizontalAdvance("●") + layout.spacing()
        layout.setContentsMargins(
            self._base_margins.left() + self._glyph_width,
            self._base_margins.top(),
            self._base_margins.right(),
            self._base_margins.bottom(),
        )
        # The buttons are sized from the same metric and so go stale with it.
        # Guarded because `_apply_text_metrics` runs from `__init__` before the
        # buttons exist, and again on every later font change when they do.
        if hasattr(self, "start_button"):
            self._fit_buttons()

    def show_error(self, message: str) -> None:
        """Put a failure under this row's controls.

        Announced as part of the row rather than as a separate control: it is
        not interactive, and a screen-reader user reaching it by Tab would have
        found a stop with nothing to do.
        """
        if self._error is None:
            self._error = QLabel(self)
            # PlainText for the reason the cells are: a failure interpolates a
            # project's own name and a launcher's own error string.
            self._error.setTextFormat(Qt.TextFormat.PlainText)
            self._error.setWordWrap(True)
            self._error.setFont(self.font())
            self._outer_layout.addWidget(self._error)
        self._error.setText(message)
        self._error.show()

    def clear_error(self) -> None:
        """Destroy the label rather than blanking it — see `__init__` on why an
        empty one may not be left in the accessibility tree."""
        if self._error is None:
            return
        self._outer_layout.removeWidget(self._error)
        self._error.deleteLater()
        self._error = None

    def error_rect(self) -> QRect | None:
        """Where the failure is on SCREEN, or None if none is shown.

        In global coordinates because that is the only frame in which "next to
        the row that raised it" can be checked — a widget can be inside the
        right parent and painted nowhere near it.
        """
        if self._error is None:
            return None
        return QRect(self._error.mapToGlobal(QPoint(0, 0)), self._error.size())

    def _fit_buttons(self) -> None:
        """Each button as wide as its own label, not the style's default.

        `design.md § Accessibility` budgets the whole row — name, state, port
        AND controls — to one lens view of `READABLE_BAND_PX`, and Fusion's
        `QPushButton` has a minimum width of 80 px whatever it says. Four of
        them spent 344 px of that budget on four words needing about half,
        which put a real sibling's row (`Ants_Projects_Hub_Website`) at 641 px
        — outside the lens, so reading one row meant panning (LWSM-1032).

        From the text metric and re-run on every render, never a pixel
        constant (`§ O7`): the label changes with the language and its width
        changes with the text-size control, and a width settled once would be
        wrong after either. `MIN_TARGET_PX` is a floor rather than a size, so a
        translation that returns an empty string cannot produce a target too
        small to hit.
        """
        metrics = self.fontMetrics()
        # Breathing room derived from the font as well, so it grows with the
        # label rather than pinching it at 200 %.
        padding = metrics.horizontalAdvance("MM")
        for button in (
            self.start_button,
            self.stop_button,
            self.restart_button,
            self.open_button,
        ):
            button.setFixedWidth(
                max(metrics.horizontalAdvance(button.text()) + padding, MIN_TARGET_PX)
            )

    def natural_widths(self) -> tuple[int, int, int]:
        """What this row's three cells would each need on their own.

        Derived from the text currently rendered, never from the width already
        applied — see `_apply_text_metrics` on why reading the floor back would
        ratchet the column.
        """
        return (
            max(self._state_floor, self._state.sizeHint().width()),
            self._name.sizeHint().width(),
            max(self._port_floor, self._port.sizeHint().width()),
        )

    def apply_column_widths(self, widths: tuple[int, int, int]) -> None:
        """Adopt the shared column geometry `MainWindow` computed (LWSM-1145).

        Rows are created once and updated in place (LWSM-1131), so this is
        re-applied after every update rather than settled at construction.
        """
        for label, width in zip(
            (self._state, self._name, self._port), widths, strict=True
        ):
            label.setFixedWidth(width)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._apply_text_metrics()

    def matches(self, needle: str) -> bool:
        """Whether this row survives the filter (LWSM-1040).

        `casefold`, not `lower`: a project name is a directory name, and the
        case the filesystem holds is not always the case the user types.

        Name only, deliberately. Filtering on the port as well would make a row
        appear and disappear as its port is detected or lost, which is a list
        that moves under a magnifier for reasons the user did not cause.
        """
        if not needle:
            return True
        view = self._view
        return view is not None and needle in view.name.casefold()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Enter starts or stops this project (LWSM-1040).

        It CLICKS the button rather than calling the controller, so which
        action is legal in which state stays stated once, in
        `_apply_button_state`. A second copy of that rule here would be free to
        drift from the buttons this key press stands in for — and both overlay
        states disable Start and Stop together, so Enter correctly does nothing
        mid-transition without naming the states at all.

        Start is offered before Stop because they are mutually exclusive:
        `_apply_button_state` enables Start only when not running and not in
        transition, and Stop only when running. The order is what happens when
        neither is enabled, not a precedence between two live actions.
        """
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            for button in (self.start_button, self.stop_button):
                if button.isEnabled():
                    button.click()
                    event.accept()
                    return
        super().keyPressEvent(event)

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
            # Centred on the STATE CELL rather than on the row, which are the
            # same rectangle until a failure line is shown and are not
            # afterwards — the glyph would drift down the taller row and sit
            # beside nothing (LWSM-1032).
            QRect(
                self._glyph_x,
                self._state.y(),
                self._glyph_width,
                self._state.height(),
            ),
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

    def _apply_button_state(self, row: RowView) -> None:
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
        self.open_button.setText(QCoreApplication.translate(_TR_CONTEXT, "Open"))
        status = row.status
        in_transition = status in (ProjectStatus.STARTING, ProjectStatus.STOPPING)
        running = status is ProjectStatus.RUNNING
        # `not in_transition` appears once, on Start, and that is not an
        # oversight on the other three. The overlay REPLACES the status, so
        # `running` and `in_transition` are mutually exclusive — a guard on
        # Stop, Restart or Open would be dead code, and a mutation removing it
        # survived every test, which is what a redundant condition looks like
        # from the outside. Start is the one that needs it: `not running` is
        # true while starting, so without the guard a second click would spawn
        # a second server (`coding.md § 1.1`).
        self.start_button.setEnabled(not in_transition and not running)
        self.stop_button.setEnabled(running)
        self.restart_button.setEnabled(running)
        # Running AND ours. ADR-0004 carries the threat model and governs here
        # (user decision, 2026-08-15): `chdir()` is free, so any local process
        # can bind a project's port and be classified `running`, and opening a
        # browser on it is localhost phishing with this app's credibility behind
        # it. The ADR's full mitigation is a disclosure dialog naming the
        # holder's path, uid, cmdline and start time — which needs the
        # seven-state model P06 adds, since `_classify` cannot yet tell foreign
        # from managed. Until then Open is restricted to servers this manager
        # started, which the supervisor's own running set answers exactly
        # (LWSM-1141).
        #
        # **Not** enabled while starting: there is no bound port yet, so the
        # browser would open on nothing and the user would blame the app rather
        # than the wait.
        self.open_button.setEnabled(running and row.managed)
        # An accessible name of its own on each, because the label alone reads
        # as "Start" three times over in a list of three projects (`§ O8`).
        for button, verb in (
            (self.start_button, "Start %1"),
            (self.stop_button, "Stop %1"),
            (self.restart_button, "Restart %1"),
            (self.open_button, "Open %1 in a browser"),
        ):
            button.setAccessibleName(
                QCoreApplication.translate(_TR_CONTEXT, verb).replace(
                    "%1", self._name.text()
                )
            )
        # Last, because it measures the labels this method has just set.
        self._fit_buttons()

    def apply_theme(self, theme: Theme) -> None:
        """Adopt a new palette and re-render (LWSM-1031).

        The `update_from` short-circuit caches `_glyph_color`, and LWSM-1111
        named this as the live edge the day the palette could change: a theme
        swap with an unchanged `RowView` would leave the glyph painted in the
        old palette while the *word* follows the new one, because the word is
        restyled by the sheet and the glyph is painted from that cached value.
        Going through `_rerender` is the fix that comment predicted.

        The focus ring needs no separate step: `paintEvent` reads
        `self._theme.focus_ring_color()`, and `_rerender` requests the repaint.
        """
        self._theme = theme
        self._rerender()

    def retranslate(self) -> None:
        """Re-render every cell from the `RowView` already held.

        `update_from` short-circuits on an unchanged view (LWSM-1076), which is
        right for a poll tick and wrong for a language change: the data did not
        change, the words for it did. Without this a translator installed
        *after* the window was built never reached an existing row, while a row
        built afterwards rendered translated — so § 4.4's stated reason for
        translating at call time was untrue as written (LWSM-1107).
        """
        self._rerender()

    def _rerender(self) -> None:
        """Re-run `update_from` past its own equality guard.

        Shared by `retranslate` and `apply_theme` because both change how the
        held `RowView` should be *rendered* without changing the view itself,
        which is exactly the case the guard is wrong for. `update()` runs even
        with no view held, so a row that has never been populated still
        repaints its ring in the new palette.
        """
        view, self._view = self._view, None
        if view is not None:
            self.update_from(view)
        self.update()

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
        # The state has moved on, so a failure describing the old one is now a
        # lie — and a magnifier user reading one row at a time has nothing else
        # on screen to contradict it (LWSM-1032). Cleared here rather than on a
        # timer: what makes the message stale is the state changing, and that
        # is exactly what reaching this line means.
        self.clear_error()

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
        self._apply_button_state(row)

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
        announced = f"{self._state.text()}, {self._name.text()}, {self._port.text()}"
        name_changed = announced != self.accessibleName()
        self.setAccessibleName(announced)
        # Qt does NOT notify AT-SPI when an accessible name changes, so
        # `setAccessibleName` alone left `design.md § Accessibility`'s "a state
        # change announces itself once" unimplemented — a screen reader was
        # never told (LWSM-1076).
        #
        # Gated on the NAME, not only on the RowView equality check above. That
        # check was sufficient while every field rendered as text; `managed`
        # (LWSM-1141) renders as button enablement and nothing else, so a
        # project leaving the supervisor's set now changes the view without
        # changing a word of what a screen reader would read out — and an
        # announcement of an unchanged name is the once-a-second re-announcement
        # that check exists to prevent, arriving by a third route.
        if name_changed:
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
        open_url: Callable[[QUrl], bool] | None = None,
        open_settings: Callable[[], None] | None = None,
        save_theme: Callable[[str], None] | None = None,
        text_scale: int = MIN_TEXT_SCALE,
        save_text_scale: Callable[[int], None] | None = None,
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
        # `ProjectController._stopped`, on the window's own worker. Set by
        # `shutdown()` and checked in the rescan slots, because a merge that
        # finishes after teardown would otherwise run `save()` and
        # `set_records()` against an already-torn-down window and controller —
        # INV-16's race, one pool along (LWSM-1139). Cutting the connections
        # instead cannot close it: a `QMetaCallEvent` already posted is
        # dispatched regardless of any later disconnect (LWSM-1098).
        self._stopped = False
        # Injected so the tests never open a real modal: a `QMessageBox.exec()`
        # in a test blocks the event loop with nothing to click it, which is a
        # hang rather than a failure.
        self._confirm = confirm if confirm is not None else self._confirm_dialog
        # Injected for the same reason as `confirm`: a test that reached
        # `QDesktopServices.openUrl` would launch the developer's browser.
        self._open_url = open_url if open_url is not None else QDesktopServices.openUrl
        # The third injected seam, and the reason LWSM-1146 could land without
        # LWSM-1018: this item owns the BAR, not the dialog. The dialog arrives
        # as an argument rather than as an edit to `_build_menus`.
        self._open_settings = (
            open_settings if open_settings is not None else self._settings_unavailable
        )
        # The fourth seam, and the one that defaults to doing NOTHING rather
        # than to the real thing. `confirm` and `open_url` can default to the
        # real behaviour because a test that never triggers them never reaches
        # it; this one would write to the developer's own
        # ~/.config/localwebservermanager/settings.json the moment a test
        # exercised the picker. `build_window` injects the real saver, the way
        # it already injects `rescan` and `load`.
        self._save_theme = save_theme
        # The fifth seam, same shape and same reason as `save_theme`: a test
        # that exercises the picker must not write to the developer's own
        # settings.json. Kept separate from `save_theme` rather than widened
        # into one `save(Settings)` because this window does not hold a
        # `Settings` — it is given a `Theme`, which carries no id — and the
        # merge that stops one field overwriting the other belongs where the
        # file is read, which is `__main__`.
        self._save_text_scale = save_text_scale
        # The size the DESKTOP asked for, captured before we scale anything, so
        # every later step multiplies it rather than the size now on screen —
        # otherwise 150 % then 200 % lands at 300 % and 100 % never returns.
        # It assumes the application font is still the desktop's when the
        # window is built, which holds because `build_window` runs once per
        # process and applies the stored scale through this window.
        app = QApplication.instance()
        self._base_point_size = app.font().pointSizeF() if app is not None else 0.0
        self._text_scale = MIN_TEXT_SCALE
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
        # Before the central widget, because `_apply_default_geometry` measures
        # the bar as chrome the list does not get.
        self._build_menus()

        central = QWidget(self)
        outer = QVBoxLayout(central)
        # Margins and gaps from the text metric, never a pixel constant
        # (`§ O7`): the window that reads as comfortable at 100 % is cramped at
        # 200 %, which is exactly the setting LWSM-1032's control offers.
        gap = self.fontMetrics().height()
        outer.setContentsMargins(gap, gap, gap, gap)
        outer.setSpacing(gap)
        # ONE strip carrying both controls (LWSM-1040), not one strip each.
        # Every row of chrome is a row the list does not get, and this window
        # is read through a magnifier — so the filter box joins the strip
        # LWSM-1149 already built rather than taking a second one.
        # `_apply_default_geometry` measures the strip whole for that reason.
        #
        # Created before the scroll area and after the menu bar, because Qt's
        # default tab order follows construction order among siblings and
        # `design.md § Accessibility` requires tab order to follow visual
        # order.
        self._filter = QLineEdit(central)
        self._filter.textChanged.connect(self._apply_filter)
        strip = QHBoxLayout()
        strip.addWidget(self._filter)
        # Between the two controls, so the filter keeps its natural width at
        # the left and Rescan stays pinned right.
        strip.addStretch(1)
        self._rescan_button: QPushButton | None = None
        self._rescan_pool: QThreadPool | None = None
        self._rescan_signals: _RescanSignals | None = None
        if self._rescan is not None:
            self._rescan_button = QPushButton(self._rescan_label(), central)
            # Visual order is tab order, and the button is a real QPushButton so
            # it is focusable and carries its own accessible name from its text
            # (`§ O8`).
            # Pushed to the right rather than a control stretched across the
            # whole window (LWSM-1149). A full-width button reads as the
            # window's primary purpose, and rescanning is not what the user
            # came here to do.
            strip.addWidget(self._rescan_button)
            self._rescan_button.clicked.connect(self._start_rescan)
            # A private pool, not the global instance: teardown must wait for
            # this window's own worker and nothing else, which is
            # `ProjectController`'s reasoning on its poll.
            self._rescan_pool = QThreadPool(self)
            self._rescan_pool.setMaxThreadCount(1)
            self._rescan_signals = _RescanSignals(self)
            self._rescan_signals.done.connect(self._on_rescan_done)
            self._rescan_signals.failed.connect(self._on_rescan_failed)
        # After the branch: the strip is added whether or not it got a button,
        # because the filter box is in it either way.
        outer.addLayout(strip)
        self._strip = strip
        self._retranslate_filter()
        # The list scrolls (LWSM-1149). Without this the window's minimum
        # height is every row it holds, so a user with twenty projects gets a
        # window taller than the screen that cannot be shrunk — the opposite
        # failure to the one this item was filed for, and worse.
        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.addStretch(1)
        self._scroll = QScrollArea(central)
        self._scroll.setWidgetResizable(True)
        # No frame: the rows are already framed, and a box round the box is the
        # chrome this item exists to remove.
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._rows_host)
        outer.addWidget(self._scroll, 1)
        self.setCentralWidget(central)

        self._rows: dict[Path, ProjectRow] = {}
        self._geometry_applied = False
        # Before `_sync_rows`, and the order is load-bearing at both ends. The
        # menu must already exist, because a scale restored from settings.json
        # arrives with no action triggered and has to set its own checkmark.
        # And the geometry must NOT have been applied yet: `_sync_rows` sizes
        # the window to its rows, so scaling afterwards leaves a window
        # measured for 100 % text holding 175 % text. `changeEvent` reaches
        # `_align_columns` from here with no rows yet, which returns early.
        self.set_text_scale(text_scale, remember=False)
        self._sync_rows()
        controller.projects_changed.connect(self._sync_rows)
        controller.action_failed.connect(self._report_failure)
        controller.confirmation_required.connect(self._ask_to_trust)

        if notices:
            self.set_status_message(self._notice_summary(notices))

    def _build_menus(self) -> None:
        """The bar every later item hangs off (LWSM-1146).

        The window had one Rescan button and nowhere else to put anything, so
        this exists to be attached to: themes (LWSM-1031), Centre on screen
        (LWSM-1033), logs (P08), quit-to-tray (P09). It owns the bar only —
        the settings dialog is LWSM-1018's, and reaches this through
        `_open_settings` rather than through an edit to this method.

        Every label carries an `&` mnemonic, so the bar is keyboard-reachable
        as it stands (`§ O8` clause 2); LWSM-1040 owns keyboard access proper
        and this must not foreclose it. A `QAction`'s accessible name comes
        from its text, which is clause 1, and the text is the state, which is
        clause 3. The labels are set in `_retranslate_menus` rather than here
        so that one method is the whole answer to LanguageChange.
        """
        bar = self.menuBar()
        self._file_menu = bar.addMenu("")
        # No rescan context, no entry — the same rule the button follows, and
        # for the same reason: an enabled control that cannot work is worse
        # than an absent one.
        self._rescan_action: QAction | None = None
        if self._rescan is not None:
            self._rescan_action = self._file_menu.addAction("")
            self._rescan_action.triggered.connect(self._start_rescan)
            self._file_menu.addSeparator()
        self._quit_action = self._file_menu.addAction("")
        # The platform's own quit sequence rather than a literal, so it is
        # whatever the desktop already taught the user.
        self._quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._quit_action.triggered.connect(self.close)

        self._settings_menu = bar.addMenu("")
        self._build_theme_menu(self._settings_menu)
        self._build_text_size_menu(self._settings_menu)
        self._settings_menu.addSeparator()
        self._settings_action = self._settings_menu.addAction("")
        self._settings_action.triggered.connect(self._open_settings)
        self._retranslate_menus()

    def _build_theme_menu(self, parent: QMenu) -> None:
        """The theme picker (LWSM-1031), a submenu of Settings.

        A submenu rather than a third top-level menu: the bar has File and
        Settings, and which palette is on screen is a setting. It sits ABOVE
        Preferences because it is the entry that works today.

        Grouped by `is_dark` and then `high_contrast`, with a separator between
        — which is what those two flags are for. The assistive palettes come
        last and together, because they are a tool rather than a taste.

        One exclusive `QActionGroup`, so the checkmark is the stored choice
        rather than something that has to be cleared by hand. Labels come from
        the theme's own `label`, which is data and deliberately not translated
        (finbreak's INV-13): a palette name is not a sentence.
        """
        self._theme_menu = parent.addMenu("")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}

        def rank(item: tuple[str, Theme]) -> tuple[int, int]:
            """Three groups: light, dark, assistive. Not four.

            The two assistive palettes are a light one and a dark one, so
            ranking on `high_contrast` and `is_dark` independently puts a
            separator between them — and they belong together, because what
            they have in common (a 7:1 floor, an assistive purpose) matters
            more here than which of them is dark.
            """
            _name, theme = item
            if theme.high_contrast:
                return (2, 0)
            return (0, 1 if theme.is_dark else 0)

        previous: tuple[int, int] | None = None
        for name, theme in sorted(THEMES.items(), key=rank):
            group = rank((name, theme))
            if previous is not None and group != previous:
                self._theme_menu.addSeparator()
            previous = group
            action = self._theme_menu.addAction(theme.label)
            action.setCheckable(True)
            action.setChecked(theme is self._theme)
            # `name`, not the loop variable: a lambda closing over the loop
            # variable makes every entry select the LAST theme. That exact bug
            # shipped once here already, on the row buttons, and a one-row
            # fixture could not see it — so the test for this has all eight.
            action.triggered.connect(
                lambda _checked=False, tid=name: self.set_theme(tid)
            )
            self._theme_group.addAction(action)
            self._theme_actions[name] = action

    def _build_text_size_menu(self, parent: QMenu) -> None:
        """The in-app text-size control (LWSM-1032), beside the theme picker.

        `design.md § Accessibility` makes this a non-negotiable rather than a
        convenience: desktop-wide scaling is a blunt instrument when only one
        window needs to be bigger, and the magnifier user this app is for is
        the one who needs it. A submenu of Settings for the same reason the
        themes are one — how big the text is, is a setting.

        Five steps rather than a spin box or a slider: every step is a target a
        keyboard reaches with one key and a magnifier does not have to aim at,
        and a continuous control offers sizes nobody needs at the cost of one
        nobody can hit. `TEXT_SIZE_STEPS` spans the full 100-200 % the standard
        names — a control offering only the two ends is not a text-size
        control.

        One exclusive `QActionGroup`, so the checkmark is the stored choice
        rather than something cleared by hand — the theme picker's rule, and
        the reason `set_text_scale` can be called with no action triggered.
        """
        self._text_size_menu = parent.addMenu("")
        self._text_size_group = QActionGroup(self)
        self._text_size_group.setExclusive(True)
        self._text_size_actions: dict[int, QAction] = {}
        for percent in TEXT_SIZE_STEPS:
            action = self._text_size_menu.addAction("")
            action.setCheckable(True)
            self._text_size_group.addAction(action)
            # `percent=percent`, not a closure over the loop variable: every
            # entry would otherwise set the last step. That exact bug shipped
            # once in this file, on the row buttons (LWSM-1016).
            action.triggered.connect(
                lambda _checked=False, percent=percent: self.set_text_scale(percent)
            )
            self._text_size_actions[percent] = action

    def set_text_scale(self, percent: int, *, remember: bool = True) -> None:
        """Scale the application font to `percent` of the desktop's own size.

        On the **APPLICATION**, like the palette and for the same reason: the
        style sheet's QStyleSheetStyle re-resolves every descendant from the
        application, so setting it on the window alone reaches the frame and
        nothing inside it. `changeEvent` then pushes the new font down to every
        descendant by hand, which is the hop the style sheet breaks.

        Multiplied against `_base_point_size` rather than the current font, so
        the steps replace each other instead of compounding.

        `remember=False` is construction restoring a stored choice: there is
        nothing new to write, and writing it would turn a read into a write on
        every start. Persisting is last and its failure is reported rather than
        raised — a settings file that cannot be written must not undo a change
        the user can already see.
        """
        self._text_scale = percent
        app = QApplication.instance()
        if app is not None and self._base_point_size > 0:
            font = app.font()
            font.setPointSizeF(self._base_point_size * percent / 100)
            app.setFont(font)
        action = self._text_size_actions.get(percent)
        if action is not None:
            action.setChecked(True)
        if not remember or self._save_text_scale is None:
            return
        try:
            self._save_text_scale(percent)
        except Exception as exc:
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "The text size could not be saved: {0}"
                ).format(exc)
            )

    def _retranslate_menus(self) -> None:
        """`QCoreApplication.translate` under the file's one context, never
        `self.tr(...)`, which resolves under the *class* (LWSM-1107). The `&`
        stays inside the translated string so a translator can move the
        mnemonic to a letter that exists in their language."""
        self._file_menu.setTitle(QCoreApplication.translate(_TR_CONTEXT, "&File"))
        if self._rescan_action is not None:
            self._rescan_action.setText(
                QCoreApplication.translate(_TR_CONTEXT, "&Rescan projects")
            )
        self._quit_action.setText(QCoreApplication.translate(_TR_CONTEXT, "&Quit"))
        self._settings_menu.setTitle(
            QCoreApplication.translate(_TR_CONTEXT, "&Settings")
        )
        # The submenu's TITLE is translated; the entries inside it are theme
        # labels, which are data and are not.
        self._theme_menu.setTitle(QCoreApplication.translate(_TR_CONTEXT, "&Theme"))
        # These entries ARE translated, unlike the theme labels beside them:
        # a percentage is written differently in different locales, and the
        # placeholder is what lets a translator move the sign to the other side
        # of the number.
        self._text_size_menu.setTitle(
            QCoreApplication.translate(_TR_CONTEXT, "Te&xt size")
        )
        for percent, action in self._text_size_actions.items():
            # Qt's own %1 with `str.replace`, never `str.format` — `port_text`
            # carries the reasoning. Written here as `.format` first, and the
            # existing hostile-translation test caught it within the hour: a
            # translator returning some other string's text raised KeyError
            # out of `changeEvent`, which left every window in the process
            # half-retranslated. The rule is the file's, not that function's.
            action.setText(
                QCoreApplication.translate(_TR_CONTEXT, "%1 %").replace(
                    "%1", str(percent)
                )
            )
        self._settings_action.setText(
            QCoreApplication.translate(_TR_CONTEXT, "&Preferences...")
        )

    def set_theme(self, theme_id: str) -> None:
        """Swap the palette on the live window, then remember the choice.

        Applied in the same three places `__init__` applies it, and for the
        same reasons: the palette on the **APPLICATION** (a `self.setPalette`
        themes the window frame and nothing inside it — LWSM-1118), the style
        sheet on the window, and then every row, because a row caches its own
        theme and its glyph colour.

        Persisting is last and its failure is reported rather than raised: a
        settings file that cannot be written must not undo a switch the user
        can already see happen.
        """
        theme = theme_for_id(theme_id)
        self._theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.to_palette())
        self.setStyleSheet(theme.style_sheet())
        for row in self._rows.values():
            row.apply_theme(theme)
        action = self._theme_actions.get(theme_id)
        if action is not None:
            # The menu is not always what asked: a theme restored from
            # settings.json arrives here with no action having been triggered.
            action.setChecked(True)
        if self._save_theme is None:
            return
        try:
            self._save_theme(theme_id)
        except Exception as exc:
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "The theme could not be saved: {0}"
                ).format(exc)
            )

    def _settings_unavailable(self) -> None:
        """The honest default until LWSM-1018 lands the dialog.

        Chosen over a disabled entry: an entry that does nothing when chosen
        is indistinguishable from a broken one, and a greyed one says nothing
        about why. The status bar is already this window's notice channel.
        """
        self.set_status_message(
            QCoreApplication.translate(_TR_CONTEXT, "Settings are not available yet.")
        )

    def _set_rescan_enabled(self, enabled: bool) -> None:
        """The button and the menu entry are one control with two faces."""
        if self._rescan_button is not None:
            self._rescan_button.setEnabled(enabled)
        if self._rescan_action is not None:
            self._rescan_action.setEnabled(enabled)

    def _retranslate_filter(self) -> None:
        """The filter box's two user-visible strings (LWSM-1040).

        Its own method, and set from here rather than at construction, for the
        reason `_retranslate_menus` gives: `LanguageChange` needs one place to
        go.

        The accessible name is not the placeholder. A placeholder is erased by
        the first keystroke, so a screen-reader user who returns to a box they
        have already typed in would find it unnamed — which is the
        `setAccessibleName("")` trap from the other direction.
        """
        self._filter.setPlaceholderText(
            QCoreApplication.translate(_TR_CONTEXT, "Filter…")
        )
        self._filter.setAccessibleName(
            QCoreApplication.translate(_TR_CONTEXT, "Filter projects by name")
        )

    def _ordered_rows(self) -> list[ProjectRow]:
        """Every row in LAYOUT order — the order the user sees (LWSM-1040).

        The layout is what the user is looking at, so it is the authority on
        the order they see. `self._rows.values()` agrees with it today — both
        are insertion order, and `_sync_rows` appends to each together — but
        that is a coincidence of how rows are added rather than a property
        anything states, and no test tells the two apart. Reading the layout
        asks the question directly.
        """
        rows = []
        for index in range(self._rows_layout.count()):
            widget = self._rows_layout.itemAt(index).widget()
            if isinstance(widget, ProjectRow):
                rows.append(widget)
        return rows

    def _apply_filter(self) -> None:
        """Hide the rows the filter excludes (LWSM-1040).

        HIDDEN, never destroyed and rebuilt. INV-13 requires a row widget to be
        created once, and a filter that tore rows down would drop keyboard
        focus on every keystroke — in the one control where the user is
        certainly typing.

        Called from `_sync_rows` as well as on every keystroke, or a project
        arriving from a rescan would appear in a list the user has narrowed.
        """
        needle = self._filter.text().strip().casefold()
        for row in self._ordered_rows():
            row.setVisible(row.matches(needle))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """`/`, Escape and the number keys (LWSM-1040).

        This runs only when no focused child took the key first, and that is
        what makes the filter box safe rather than a special case: a QLineEdit
        consumes every digit and `/` it is given, so typing "1" while the caret
        is in the filter types a 1 instead of jumping to the first project. No
        guard here says so, and adding one would be dead code.

        Escape is the exception, and deliberately so — QLineEdit ignores it, so
        it arrives here from the filter box as well as from anywhere else, and
        clearing the filter is exactly what it should do in both.
        """
        key = event.key()
        if key == Qt.Key.Key_Slash:
            self._filter.setFocus(Qt.FocusReason.ShortcutFocusReason)
            # Selected, not appended to: `/` on an already-narrowed list means
            # "filter again", and the alternative is a user typing a second
            # term onto the end of the first and matching nothing.
            self._filter.selectAll()
            event.accept()
            return
        if key == Qt.Key.Key_Escape and self._filter.text():
            self._filter.clear()
            event.accept()
            return
        if (
            Qt.Key.Key_1 <= key <= Qt.Key.Key_9
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            # `isHidden`, not `isVisible`. The question is "did the filter
            # remove this row", and `isHidden` answers exactly that — it
            # tracks the flag `_apply_filter` sets and nothing else. `isVisible`
            # answers a wider one, folding in every ancestor's state, and
            # returns False for every row while the window itself is unshown.
            shown = [row for row in self._ordered_rows() if not row.isHidden()]
            index = key - Qt.Key.Key_1
            if index < len(shown):
                shown[index].setFocus(Qt.FocusReason.ShortcutFocusReason)
                event.accept()
                return
        super().keyPressEvent(event)

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
            self._retranslate_menus()
            self._retranslate_filter()
            for row in self._rows.values():
                row.retranslate()
            # A translated cell is a different width (LWSM-1145).
            self._align_columns()
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
            #
            # **Every descendant, not the rows alone** (LWSM-1032). The loop
            # here read `self._rows.values()` until 2026-08-19, which closed the
            # window-to-row hop and left the row-to-cell hop failing for the
            # identical reason: the row's font reached 18 pt while every label
            # and button inside it stayed at 9 pt, so at 200 % the state column
            # widened from 53 px to 103 px around text that never changed size.
            # The same gap left the filter box — the first control a magnifier
            # user reaches (LWSM-1040) — at 9 pt, because it is not a row.
            #
            # It survived because three tests covering this path all assert a
            # width the row DERIVES from its own font, which grows either way.
            # `test_a_text_size_change_reaches_the_text_and_not_only_the_column`
            # asserts `fontMetrics()`, the metric the widget paints with.
            #
            # A row created LATER needs nothing here: it inherits from a parent
            # whose font is now explicitly set, measured at the same 33 px.
            for widget in self.findChildren(QWidget):
                widget.setFont(self.font())
            # `setFont` delivers FontChange to the row synchronously, so every
            # floor has already been re-derived by the time this runs.
            self._align_columns()

    def _report_failure(self, path: Path, message: str) -> None:
        """A failure goes to the row it is about, and to the status bar if
        there is no such row (LWSM-1032).

        `design.md § Accessibility`: feedback surfaces next to the row or
        control that caused it, because a message in a far-off status bar is
        invisible to someone whose lens is on a button.

        The fallback is not politeness — a path can name a project that has
        since been removed, and a failure nobody sees is the one failure mode
        worse than a badly placed one.
        """
        row = self._rows.get(path)
        if row is None:
            self.set_status_message(message)
            return
        row.show_error(message)

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

    def _open_project(self, path: Path) -> None:
        """Open the running server in the desktop's browser.

        The port comes from the row the controller currently reports, not from a
        value cached when the button was created: a rescan or an override can
        move it, and opening a stale port is the confidently-wrong failure
        ADR-0003 records a sibling project having shipped.
        """
        view = next((row for row in self._controller.rows() if row.path == path), None)
        if view is None or view.effective_port is None:
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "%1 has no port to open"
                ).replace("%1", path.name)
            )
            return
        if not self._open_url(project_url(view.effective_port)):
            # openUrl returns False when the desktop has no handler. Silence
            # here would look identical to a browser that opened behind the
            # window.
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "Could not open a browser for %1"
                ).replace("%1", path.name)
            )

    @staticmethod
    def _rescan_label() -> str:
        return QCoreApplication.translate(_TR_CONTEXT, "Rescan")

    def shutdown(self) -> None:
        """Delivery refused, then a bounded wait for the rescan worker.

        Called beside `controller.stop()`, and deliberately the same shape.
        Without it a pool thread finishes into a window being torn down, which
        is the flake `testing.md § T5` exists to prevent — and `~QThreadPool`
        joins with **no** timeout, so the cost of not doing it is invisible to
        pytest's own number and shows up only as process wall time.

        Two halves, and until LWSM-1139 it had neither. **The wait was not
        bounded**: on timeout it logged the word "abandoning" and returned,
        leaving the pool parented to the window, so `~QThreadPool` ran the
        unbounded join anyway and `__main__`'s claim that this "gets the same
        bounded wait" was false. `abandon_pool` is what makes it true, and it is
        `stop()`'s own mechanism rather than a second copy of it. **And nothing
        refused delivery**: a rescan landing after teardown still ran `save()`
        and `set_records()`.

        Idempotent: the pool is taken here, so a second call has nothing left to
        wait for and `_start_rescan` refuses for the same reason.
        """
        self._stopped = True
        self._rescan_in_flight = False
        pool, self._rescan_pool = self._rescan_pool, None
        if pool is None or pool.waitForDone(RESCAN_STOP_WAIT_MS):
            return
        log.warning(
            "a rescan was still running after %d ms; abandoning it so the app can quit",
            RESCAN_STOP_WAIT_MS,
        )
        abandon_pool(pool)

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
        self._set_rescan_enabled(False)
        self._rescan_pool.start(
            _RescanTask(self._rescan, self._controller.records(), self._rescan_signals)
        )

    def _finish_rescan(self, message: str) -> None:
        self._rescan_in_flight = False
        self._set_rescan_enabled(True)
        self.set_status_message(message)

    def _on_rescan_failed(self, detail: str) -> None:
        if self._stopped:
            # The window is being torn down; there is nobody left to tell.
            return
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

        `_finish_rescan` runs in a `finally`, and the body carries a catch-all
        (LWSM-1135). It is the ONLY place `_set_rescan_enabled(True)` happens
        — which re-enables the button and the menu entry together since
        LWSM-1146 — and this slot is delivered from the pool thread — so PySide6
        swallows anything escaping it, emitting no signal and telling the user
        nothing. A raw `OSError` out of `save_projects` therefore discarded the
        merge silently AND left Rescan disabled for the rest of the session.
        `_RescanTask.run`'s guard, one thread along, and `BaseException` for
        its reason: reported here or nowhere.

        The `_stopped` guard comes first and is not tidiness: `_apply_rescan`
        writes `projects.json` and calls `set_records` on the controller, so a
        merge landing after `shutdown()` saved over the user's project list on
        the way out (LWSM-1139).
        """
        if self._stopped:
            return
        message = ""
        try:
            message = self._apply_rescan(merged)
        except BaseException as exc:
            log.exception("the rescan could not be applied")
            message = QCoreApplication.translate(
                _TR_CONTEXT, "Rescan failed: %1"
            ).replace("%1", f"{type(exc).__name__}: {exc}")
        finally:
            self._finish_rescan(message)

    def _apply_rescan(self, merged: MergeResult) -> str:
        """The write and the UI update, returning the status-bar message.

        Split out of `_on_rescan_done` so that slot is nothing but the
        always-finish guard above — a body and its own `finally` in one
        function is where the missing re-enable hid in the first place.
        """
        if self._rescan is None:
            return ""
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
        return message

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
                widget.open_button.clicked.connect(
                    lambda _checked=False, p=path: self._open_project(p)
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

        # Before the geometry: a row arriving under an active filter must not
        # show up in a list the user has already narrowed.
        self._apply_filter()
        self._align_columns()
        self._apply_default_geometry()

    def _apply_default_geometry(self) -> None:
        """Open big enough to read (LWSM-1149).

        A first run has nothing remembered — restoring a geometry the user
        chose is LWSM-1033's — so this is the only impression a new user gets,
        and Qt's own default was ~790x520 with the list crushed against the
        window chrome.

        Measured from the content and clamped to the screen, never set from a
        pixel constant (`§ O7`): a size that fits this display truncates the
        next one, and one that fits 100 % text truncates 200 %. The two counts
        below are counts of rows, and the height they imply is measured off a
        real row.

        Applied once. It runs from `_sync_rows` rather than only from
        `__init__` because a first run has no records yet and the rows arrive
        with the first scan — but a second application would fight a window the
        user had already resized.
        """
        if self._geometry_applied:
            return
        rows = list(self._rows.values())
        if not rows:
            return
        self._geometry_applied = True

        outer = self.centralWidget().layout()
        margins = outer.contentsMargins()
        row_height = rows[0].sizeHint().height() + max(self._rows_layout.spacing(), 0)
        # Everything that is not the list — the menu bar included (LWSM-1146),
        # or the window opens one bar too short and a list that fits scrolls.
        chrome = (
            margins.top()
            + margins.bottom()
            + self.menuBar().sizeHint().height()
            + self.statusBar().sizeHint().height()
        )
        # The STRIP, not the button in it. The filter box is the taller of the
        # two on most styles, so measuring the button would under-count the
        # chrome by the difference and open the window that much short — the
        # LWSM-1146 menu-bar mistake, one control along. The strip is
        # unconditional now, so this is too.
        chrome += self._strip.sizeHint().height() + outer.spacing()
        # The scrollbar's width is reserved rather than discovered: it appears
        # the moment the list is longer than the window, and a width that did
        # not allow for it would take that room out of the last column.
        width = (
            self._rows_host.sizeHint().width()
            + self._scroll.verticalScrollBar().sizeHint().width()
            + margins.left()
            + margins.right()
        )

        want = QSize(width, chrome + min(len(rows), DEFAULT_VISIBLE_ROWS) * row_height)
        # The columns are fixed-width, so there is no narrower window in which
        # they do not collide — the floor is the content itself, and only the
        # height is negotiable.
        floor = QSize(width, chrome + MIN_VISIBLE_ROWS * row_height)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry()
            cap = QSize(int(room.width() * 0.9), int(room.height() * 0.9))
            want = want.boundedTo(cap)
            floor = floor.boundedTo(cap)
        self.setMinimumSize(floor)
        self.resize(want)

    def _align_columns(self) -> None:
        """One width per column across every row, the widest cell winning.

        Each `ProjectRow` owns its own `QHBoxLayout` and Qt syncs nothing
        between sibling layouts, so with seven projects the four buttons landed
        at a different x on every row and the eye had nothing to track down
        (LWSM-1145). Shared geometry rather than a fixed pixel width per column,
        which breaks the moment a project has a long name or the font scales.

        Called after every `_sync_rows` and after a language or font change,
        because all three change what a cell needs.
        """
        rows = list(self._rows.values())
        if not rows:
            return
        natural = [row.natural_widths() for row in rows]
        widths = (
            max(cells[0] for cells in natural),
            max(cells[1] for cells in natural),
            max(cells[2] for cells in natural),
        )
        for row in rows:
            row.apply_column_widths(widths)
