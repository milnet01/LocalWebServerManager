"""The window: one row per project, each stating its status as a word.

UI layer. Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`.

Two rules this file exists to obey. `docs/standards/coding.md § O7`: no colour
literal, no font family, no pixel constant — colours come from `Theme` tokens
and sizes from the text metric. `§ O8`: every row lands with an accessible
name, keyboard reachability, its state as text, and a layout that reflows.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
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
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from lwsm import __version__, applog, browsers, placement, registry, scanner
from lwsm.configfile import ConfigFileError
from lwsm.controller import (
    ProjectController,
    ProjectStatus,
    RowView,
    abandon_pool,
)
from lwsm.placement import Rect, centre_in
from lwsm.registry import LoadResult, MergeResult, ProjectRecord, RegistryError
from lwsm.settings import MAX_TEXT_SCALE, MIN_TEXT_SCALE
from lwsm.theme import THEMES, Theme, theme_for_id

log = applog.get_logger(__name__)

# How long to wait for a rescan worker at teardown. The same bounded shape
# `controller.stop()` uses, and for the same reason: an unbounded wait turns a
# slow scan into an app that cannot be quit.
# `place_window`'s signature is keyword-heavy on purpose, and a test
# substitutes it with a `functools.partial` of itself, so the alias says what
# comes BACK — the rectangle actually asked for, or `None` where placement is
# unavailable — and leaves the arguments to the function's own definition.
PlaceWindow = Callable[..., "Rect | None"]

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
# The largest fraction of a screen this window opens at. Not a pixel size
# (`§ O7`): the point is that it is relative to whatever display is attached
# now, which is the one thing a size recorded on a different monitor is not.
SCREEN_FRACTION = 0.9

# Decorative only. One of the three signals design.md § Accessibility requires,
# and excluded from the accessible name — a screen reader announcing "black
# circle, running" is noise wearing the costume of redundancy.
# The browser column is capped at this many average characters. A cap rather
# than a natural width because LWSM-1174 is open and says a long project name
# already pushes the buttons out of reach unrecoverably -- so a column that grew
# with its content would make a live defect worse. Measured in characters and
# resolved through the font metric, never in pixels (`§ O7`), so the 100-200 %
# text-size control still reaches it.
BROWSER_COLUMN_CHARS = 10

# The name column is capped at this many average characters and elided past it
# (LWSM-1174, needed by LWSM-1187). Uncapped, a long project name pushed the
# whole row's controls out of the ~600 px lens a magnifier user reads through,
# with no way to recover -- measured 2026-08-24 at 593 px for a 30-character
# name, 7 px inside the limit before a browser column existed at all.
# `design-accessibility.md` derives that band from who this app is for, so it
# is the name that gives way, not the controls.
NAME_COLUMN_CHARS = 16

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

# The trust prompt's placeholders, matched so all three can be substituted on
# one pass (LWSM-1181). Sequential `.replace` calls let the first value land in
# a template that still held the other two.
_TRUST_FIELD = re.compile(r"%[123]")


def _no_line_breaks(value: str) -> str:
    """A value from someone else's tree, rendered so it cannot forge layout.

    `_confirm_dialog` is one plain-text block whose headings are its only
    structure, and all three of its fields are names a stranger may have
    chosen. A line break in one lets it draw a heading of its own.
    """
    return value.replace("\r", "\\r").replace("\n", "\\n")


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


def hidden_name(name: str) -> str:
    """A hidden project's name, as it reads while the toggle is showing them.

    Translated at call time like every other cell, so a language change reaches
    a row that already exists (LWSM-1107).
    """
    return QCoreApplication.translate(_TR_CONTEXT, "%1 (hidden)").replace("%1", name)


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


def _merge_parts(counts: dict[str, int]) -> list[str]:
    """The rendered outcome fragments, in a fixed order, omitting zeroes.

    Split out of `summarise_merge` by LWSM-1148 so an import can render the
    same counts under its own leading word. Both leading words stay literals
    at their own call site rather than becoming an argument, because `lupdate`
    extracts literals and an interpolated one is a string no translator sees.
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
    return parts


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
    parts = _merge_parts(counts)
    if not parts:
        return QCoreApplication.translate(_TR_CONTEXT, "Rescan: no changes")
    return QCoreApplication.translate(_TR_CONTEXT, "Rescan: %1").replace(
        "%1", ", ".join(parts)
    )


def summarise_import(counts: dict[str, int]) -> str:
    """The same counts under the import's leading word (LWSM-1148).

    An import produces only `new`, `changed`, `unchanged` and the duplicate
    flag, so the four remaining fragments are always zero and always omitted —
    `_merge_parts` needs no import-specific ordering.
    """
    parts = _merge_parts(counts)
    if not parts:
        return QCoreApplication.translate(_TR_CONTEXT, "Import: no changes")
    return QCoreApplication.translate(_TR_CONTEXT, "Import: %1").replace(
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

    def __init__(
        self,
        row: RowView,
        theme: Theme,
        parent: QWidget | None = None,
        available_browsers: tuple[browsers.Browser, ...] = (),
    ):
        super().__init__(parent)
        self._theme = theme
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # Qt's own context menu, not a `contextMenuEvent` of ours (LWSM-1185).
        # `ActionsContextMenu` renders the widget's actions on right-click and
        # on the Menu key, so the row is menu-reachable from the keyboard with
        # nothing here saying so — and there is no `menu.exec()` of ours for a
        # test to have to avoid, which is what an untestable wiring looks like.
        self.hide_action = QAction(self)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.addAction(self.hide_action)

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
        # The name as it should READ, before elision fits it to the column.
        # Set before `_apply_text_metrics`, which measures it.
        self._name_display = row.name
        # The column width `apply_column_widths` last handed down. Held rather
        # than read back from the label: `setFixedWidth` does not update
        # `width()` until Qt runs a layout pass, so eliding against `width()`
        # immediately after setting it measures the PREVIOUS width -- which
        # elided "alpha" to "alp…" in a 33 px column.
        self._name_width = 0
        # Scanned once by MainWindow and handed down, never rescanned per row:
        # the scan reads every desktop entry on the machine (381 of them here),
        # and a row is rebuilt on every rescan.
        self._browsers = available_browsers

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

        # Which browser Open uses for THIS project (LWSM-1187). A control among
        # the cells rather than a context-menu entry, on the user's own decision
        # -- it is a per-project setting they want to see at a glance, not one
        # to go hunting for.
        #
        # The first entry is the desktop default and is always present. A
        # project with no choice and a project whose chosen browser has since
        # been uninstalled both land on it, so an uninstalled browser degrades
        # to "the default" rather than to a phantom entry that cannot launch.
        # Its text is set in `update_from`, so a language change reaches it.
        self.browser_box = QComboBox(self)
        self.browser_box.addItem("", "")
        for browser in self._browsers:
            self.browser_box.addItem(browser.name, browser.entry_id)
        layout.addWidget(self.browser_box)
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
        self._name_cap = metrics.horizontalAdvance("x") * NAME_COLUMN_CHARS
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
        # The browser column is FIXED and capped -- see `BROWSER_COLUMN_CHARS`.
        # It therefore does NOT join `natural_widths`' tuple: every row gets the
        # same width from the same font, so the column is aligned by
        # construction and there is nothing for `_align_columns` to reconcile.
        # Guarded for `start_button`'s reason -- this runs from `__init__`
        # before the widgets exist.
        if hasattr(self, "browser_box"):
            widest = max(
                (metrics.horizontalAdvance(b.name) for b in self._browsers),
                default=0,
            )
            cap = metrics.horizontalAdvance("x") * BROWSER_COLUMN_CHARS
            # The arrow is furniture the text may not overlap; taken from the
            # style rather than guessed, so it follows the platform.
            arrow = self.browser_box.style().pixelMetric(
                QStyle.PixelMetric.PM_ScrollBarExtent
            )
            self.browser_box.setFixedWidth(min(widest, cap) + arrow + layout.spacing())
            self.browser_box.setMinimumHeight(MIN_TARGET_PX)

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
            # The HEIGHT needs the same floor, and CI is what proved it. The
            # style derives a button's height from the font, so on this
            # developer's machine they came out 25 px and cleared 24 by one
            # pixel — while the runner, whose default font is smaller, made
            # them **22**. That is not a test artefact: it is the promise
            # failing on any machine with a small system font, which is a
            # machine a magnifier user may well be on. A minimum rather than a
            # fixed height, so it still grows with the text-size control.
            button.setMinimumHeight(MIN_TARGET_PX)

    def natural_widths(self) -> tuple[int, int, int]:
        """What this row's three cells would each need on their own.

        Derived from the text currently rendered, never from the width already
        applied — see `_apply_text_metrics` on why reading the floor back would
        ratchet the column.
        """
        return (
            max(self._state_floor, self._state.sizeHint().width()),
            # From the FULL name, never from the label: the label holds the
            # elided string, so reading its size hint back would shrink the
            # column, which would elide harder, which would shrink it again --
            # the ratchet this method's docstring warns about, running the other
            # way. Capped per LWSM-1174.
            min(
                self.fontMetrics().horizontalAdvance(self._name_display),
                self._name_cap,
            ),
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
        self._name_width = widths[1]
        # Last, because it fits the name to the column this method has just set.
        self._elide_name()

    def _elide_name(self) -> None:
        """Fit the displayed name to the name column, keeping the full one.

        The label carries an elided string; `_name_display` keeps the whole one,
        and it is `_name_display` that the announcement and the tooltip read.
        That does not breach `update_from`'s cell-strings rule: what that rule
        forbids is an accessibility string DRIFTING from what is on screen, and
        elision cannot drift, because the shown string is a pure function of
        this one. The filter is untouched -- `matches` reads `RowView.name`.
        """
        metrics = self.fontMetrics()
        width = self._name_width
        # A guard, not an optimisation: `elidedText` is free to cut a string
        # whose advance merely EQUALS the width it is given, and the column is
        # set to exactly that advance for any name under the cap -- which is
        # every short name in the list.
        if not width or metrics.horizontalAdvance(self._name_display) <= width:
            elided = self._name_display
        else:
            elided = metrics.elidedText(
                self._name_display, Qt.TextElideMode.ElideRight, width
            )
        self._name.setText(elided)
        # Only when something was actually cut. A tooltip repeating the visible
        # text is noise a magnifier user has to read and dismiss.
        self._name.setToolTip(
            "" if elided == self._name_display else self._name_display
        )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._apply_text_metrics()

    def hidden_by_user(self) -> bool:
        """Whether the USER hid this project — never `QWidget.isHidden`.

        The two are one letter apart and answer opposite questions: this one is
        a stored preference, that one is whether the filter has this row off
        screen right now. A row hidden by the filter is not hidden by the user,
        and the toggle that shows hidden projects must not resurrect it.
        """
        return self._view is not None and self._view.hidden

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
                # `_name_display`, never the label: since LWSM-1174 the label
                # holds an ELIDED name, and "Start customer-dash…" is not a
                # control anybody can identify by ear.
                QCoreApplication.translate(_TR_CONTEXT, verb).replace(
                    "%1", self._name_display
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

        Says what it is rather than nulling `_view` to sneak past the guard
        (LWSM-1175). That trick worked on the guard and had collateral one line
        below it: `update_from` also clears the row's failure message, on the
        grounds that the state has moved on — which is true of a poll tick and
        false of a re-render. Both keys are the same question, so one flag
        answers both.
        """
        if self._view is not None:
            self.update_from(self._view, rerendering=True)
        self.update()

    def update_from(self, row: RowView, *, rerendering: bool = False) -> None:
        if row == self._view and not rerendering:
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
        #
        # Not on a re-render, which reaches this line with the SAME view: a
        # theme or language change invalidates nothing (LWSM-1175). The user it
        # hurt is the one switching to a high-contrast theme in order to read
        # the message they were then shown losing.
        if not rerendering:
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
        # The marker is rendered TEXT, not a colour and not an accessibility-only
        # string. Colour alone carries no meaning to a screen reader, and the
        # announcement below is built from the rendered cells precisely so no
        # accessibility string can drift from what is on screen.
        self._name_display = hidden_name(row.name) if row.hidden else row.name
        self._elide_name()
        self.hide_action.setText(
            QCoreApplication.translate(_TR_CONTEXT, "&Show this project")
            if row.hidden
            else QCoreApplication.translate(_TR_CONTEXT, "&Hide this project")
        )
        self._port.setText(port_text(row.effective_port))

        # Signals blocked: this runs once a second from the poll, and the user's
        # own `currentIndexChanged` handler writes projects.json. Without the
        # blocker every tick would rewrite the registry with the value it just
        # read -- a write loop that would look like nothing at all until the
        # disk activity was noticed.
        with QSignalBlocker(self.browser_box):
            self.browser_box.setItemText(
                0, QCoreApplication.translate(_TR_CONTEXT, "Default browser")
            )
            index = self.browser_box.findData(row.browser or "")
            # -1 means the stored browser is not installed any more. Fall back to
            # the default entry; the id stays in the file, so reinstalling the
            # browser restores the choice (`browsers.by_id` takes the same view).
            self.browser_box.setCurrentIndex(index if index >= 0 else 0)
        # Its own accessible name, for the same reason each button has one: the
        # visible label reads as "Firefox" three times over in a list of three
        # projects (`§ O8`). Not folded into the row's announcement below, which
        # is built from the CELL strings -- a control announces itself when it
        # takes focus.
        self.browser_box.setAccessibleName(
            # The full name, for the buttons' reason above.
            QCoreApplication.translate(_TR_CONTEXT, "Browser for %1").replace(
                "%1", self._name_display
            )
        )

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
        announced = f"{self._state.text()}, {self._name_display}, {self._port.text()}"
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
        list_browsers: Callable[[], tuple[browsers.Browser, ...]] | None = None,
        open_settings: Callable[[], None] | None = None,
        save_theme: Callable[[str], None] | None = None,
        text_scale: int = MIN_TEXT_SCALE,
        save_text_scale: Callable[[int], None] | None = None,
        choose_profile_to_save: Callable[[], str | None] | None = None,
        choose_profile_to_open: Callable[[], str | None] | None = None,
        position: tuple[int, int] | None = None,
        size: tuple[int, int] | None = None,
        maximized: bool = False,
        save_geometry: Callable[[Rect | None, bool, bool], None] | None = None,
        place: PlaceWindow | None = None,
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
        self._show_hidden = False
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
        # Resolved in the body, never as a default argument: a default bound to
        # the function object is captured when `def` runs and can never be
        # monkeypatched, which cost LWSM-1033 a cycle and nearly cost a second.
        #
        # Scanned ONCE, here. It reads every desktop entry on the machine (381
        # of them as measured 2026-08-24), so doing it per row or per poll would
        # put a directory walk on the once-a-second path.
        self._browsers = (
            browsers.installed if list_browsers is None else list_browsers
        )()
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
        # The sixth and seventh seams (LWSM-1148), and they default to the real
        # thing for `confirm`'s reason rather than `save_theme`'s: a file dialog
        # writes nothing by itself, and a test that never triggers one never
        # reaches it. What a test must not do is OPEN one — a real
        # `QFileDialog.getSaveFileName` in a test blocks the event loop with
        # nobody to click it, which is a hang rather than a failure. That is the
        # same hazard `SettingsDialog.choose_directory` is injected for.
        self._choose_profile_to_save = (
            choose_profile_to_save
            if choose_profile_to_save is not None
            else self._pick_profile_to_save
        )
        # LWSM-1033 / ADR-0007. Position and size arrive SEPARATELY, because
        # they are separately knowable: a Wayland session can record a size and
        # cannot record a position at all (`placement.position_is_readable`
        # carries the measurement). Joined into one rectangle, a Wayland
        # session would forget the size it does know. `maximized` is separate
        # again, because a maximised window still has a normal size to come
        # back to.
        self._remembered_pos = position
        self._remembered_size = size
        self._remembered_maximized = maximized
        self._geometry_restored = False
        # The eighth seam, and it defaults to doing nothing for `save_theme`'s
        # reason rather than `confirm`'s: this one fires on every close, so a
        # test that closed a window would write that window's geometry into the
        # developer's own settings.json — and unlike the theme picker, closing
        # is something a test does by accident.
        self._save_geometry = save_geometry
        # The ninth, and the only one defaulting to the REAL function while
        # still being injected. ADR-0007 requires the verification to be
        # behavioural — the window ends up at the coordinates, never that a
        # call was made — so a test must run the real arithmetic and the real
        # script generation. What it substitutes is one argument further down:
        # `functools.partial(place_window, environ=..., run=...)` drives the
        # Wayland branch with a stand-in for KWin and leaves everything this
        # project wrote in the path.
        #
        # `None` rather than `placement.place_window` as the default, for the
        # reason `placement_available` carries: a default argument is bound
        # when the function is DEFINED, so a `monkeypatch.setattr` on the
        # module never reaches one. That cost a cycle once in `placement.py`
        # already, and here it decides whether a `build_window` test can keep
        # its hands off the real compositor at all.
        self._place = placement.place_window if place is None else place
        self._choose_profile_to_open = (
            choose_profile_to_open
            if choose_profile_to_open is not None
            else self._pick_profile_to_open
        )
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
        # Same floor as the row's buttons, for the same reason and found by the
        # same CI run: the runner rendered this box 22 px high.
        self._filter.setMinimumHeight(MIN_TARGET_PX)
        self._filter.textChanged.connect(self._apply_filter)
        # LWSM-1156. `returnPressed` rather than a branch in the window's
        # `keyPressEvent`: a `QLineEdit` consumes Return and emits this, so the
        # key never reaches the window at all, and `ProjectRow`'s own Return —
        # which clicks that row's enabled button — keeps its meaning without
        # anything here naming it. That is Qt's propagation doing the
        # separating, the same way it already stops a digit typed into this box
        # from jumping to a project.
        self._filter.returnPressed.connect(self._focus_first_match)
        strip = QHBoxLayout()
        strip.addWidget(self._filter)
        # Between the two controls, so the filter keeps its natural width at
        # the left and Rescan stays pinned right.
        strip.addStretch(1)
        self._rescan_button: QPushButton | None = None
        self._rescan_pool: QThreadPool | None = None
        self._rescan_signals: _RescanSignals | None = None
        if self._rescan is not None:
            # Unlabelled here: `_retranslate_strip` below sets the text, so one
            # place owns it and the two cannot drift (LWSM-1177).
            self._rescan_button = QPushButton(central)
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
        self._retranslate_strip()
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
        # Profile export and import (LWSM-1148). Both entries or neither:
        # exporting needs the `LoadResult` its gate reads, importing needs the
        # registry path to write back to, and a window holding one without the
        # other cannot be built by `build_window`. Gating each on its own half
        # would put two conditions in front of one feature and state nothing
        # extra that is true.
        self._export_action: QAction | None = None
        self._import_action: QAction | None = None
        if self._rescan is not None and self._load is not None:
            self._file_menu.addSeparator()
            self._export_action = self._file_menu.addAction("")
            self._export_action.triggered.connect(self._export_profile)
            self._import_action = self._file_menu.addAction("")
            self._import_action.triggered.connect(self._import_profile)
        self._file_menu.addSeparator()
        self._quit_action = self._file_menu.addAction("")
        # The platform's own quit sequence rather than a literal, so it is
        # whatever the desktop already taught the user.
        self._quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._quit_action.triggered.connect(self.close)

        # A third top-level menu for one action, rather than folding it into
        # Settings. "Centre on screen" is something you DO, and every entry in
        # Settings is something you CHOOSE and that then stays chosen; a menu
        # whose title promises preferences should not contain a verb. It is
        # also where P08's log viewer goes.
        self._view_menu = bar.addMenu("")
        self._centre_action = self._view_menu.addAction("")
        self._centre_action.triggered.connect(self.centre_on_screen)
        # Disabled here rather than left to fail on trigger: under a Wayland
        # session with no `dbus-send` the compositor owns placement and we
        # cannot ask it, so the honest answer is an action that says why
        # (ADR-0007). The tooltip is set in `_retranslate_menus` with the label.
        self._centre_action.setEnabled(placement.placement_available())
        # Checkable, and unchecked at build: hiding is only reversible because
        # this exists, so it is offered whether or not there is a writer — a
        # project can be hidden in the file on a window that cannot save one.
        self._show_hidden_action = self._view_menu.addAction("")
        self._show_hidden_action.setCheckable(True)
        self._show_hidden_action.toggled.connect(self._set_show_hidden)

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
                    _TR_CONTEXT, "The text size could not be saved: %1"
                ).replace("%1", str(exc))
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
        if self._export_action is not None:
            self._export_action.setText(
                QCoreApplication.translate(_TR_CONTEXT, "&Export profile...")
            )
        if self._import_action is not None:
            self._import_action.setText(
                QCoreApplication.translate(_TR_CONTEXT, "&Import profile...")
            )
        self._quit_action.setText(QCoreApplication.translate(_TR_CONTEXT, "&Quit"))
        self._view_menu.setTitle(QCoreApplication.translate(_TR_CONTEXT, "&View"))
        self._centre_action.setText(
            QCoreApplication.translate(_TR_CONTEXT, "&Centre on screen")
        )
        # Only the disabled case gets an explanation — the whole point of it is
        # that the action says why rather than appearing to work.
        #
        # **`setToolTip("")` does not remove a tooltip**, in the same way
        # `setAccessibleName("")` does not hide a widget from the
        # accessibility tree: a `QAction` with an empty tooltip falls back to
        # its own TEXT, so the enabled entry reports "Centre on screen" here
        # whatever is set. Measured 2026-08-21. So the enabled branch is
        # written as the label rather than as an empty string, because that is
        # what it actually is, and the test asserts the same thing.
        self._centre_action.setToolTip(
            self._centre_action.text().replace("&", "")
            if self._centre_action.isEnabled()
            else QCoreApplication.translate(
                _TR_CONTEXT,
                "This desktop does not let an application place its own "
                "window, and KDE's window manager could not be reached.",
            )
        )
        self._show_hidden_action.setText(
            QCoreApplication.translate(_TR_CONTEXT, "Show &hidden projects")
        )
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
                    _TR_CONTEXT, "The theme could not be saved: %1"
                ).replace("%1", str(exc))
            )

    def _settings_unavailable(self) -> None:
        """What Preferences does when no opener was injected.

        LWSM-1018 landed the dialog, so the real application never reaches
        this — `build_window` always passes `open_settings`. It remains the
        default because a window built without one still has the menu entry,
        which is every `MainWindow` test that does not care about settings.

        Chosen over a disabled entry: an entry that does nothing when chosen
        is indistinguishable from a broken one, and a greyed one says nothing
        about why. The status bar is already this window's notice channel.
        """
        self.set_status_message(
            QCoreApplication.translate(_TR_CONTEXT, "Settings are not available yet.")
        )

    def _pick_profile_to_save(self) -> str | None:
        """The real Save dialog. Injected past in every test."""
        chosen, _filter = QFileDialog.getSaveFileName(
            self,
            QCoreApplication.translate(_TR_CONTEXT, "Export profile"),
            "lwsm-profile.json",
            QCoreApplication.translate(_TR_CONTEXT, "Profiles (*.json)"),
        )
        return chosen or None

    def _pick_profile_to_open(self) -> str | None:
        """The real Open dialog. Injected past in every test."""
        chosen, _filter = QFileDialog.getOpenFileName(
            self,
            QCoreApplication.translate(_TR_CONTEXT, "Import profile"),
            "",
            QCoreApplication.translate(_TR_CONTEXT, "Profiles (*.json)"),
        )
        return chosen or None

    def _export_profile(self) -> None:
        """Write the current registry to a file the user names (LWSM-1148)."""
        if self._load is None:
            return
        chosen = self._choose_profile_to_save()
        if not chosen:
            return
        try:
            registry.export_profile(
                Path(chosen), self._controller.records(), load=self._load
            )
        except RegistryError as exc:
            log.warning("the profile could not be exported: %s", exc)
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "Profile not saved: %1"
                ).replace("%1", str(exc))
            )
            return
        self.set_status_message(
            QCoreApplication.translate(_TR_CONTEXT, "Profile saved to %1").replace(
                "%1", chosen
            )
        )

    def _import_profile(self) -> None:
        """Merge a saved profile back into the registry (LWSM-1148).

        **Any refusal at load refuses the whole import**, where the registry's
        own loader deliberately keeps a row whose field was dropped. The
        asymmetry is about what each refusal costs. There, keying the gate on
        `reasons` would let one hand-typed `"port": "3000"` disable persistence
        for a whole session (LWSM-1007 § 4.3). Here the cost is one refused
        button press with a reason the user can act on — and the alternative is
        writing a silently partial user half over a good one, which is the same
        shape as the merge writing `None` over a stored port. That guarantee is
        what lets `_user_half_applied` take the user half whole, with no
        per-field qualifier.
        """
        if self._rescan is None or self._load is None:
            return
        chosen = self._choose_profile_to_open()
        if not chosen:
            return
        try:
            loaded = registry.load_projects(Path(chosen))
        except RegistryError as exc:
            self._refuse_import(str(exc))
            return
        if loaded.reasons:
            for reason in loaded.reasons:
                log.info("import: %s", reason)
            self._refuse_import(loaded.reasons[0])
            return

        merged = registry.merge_imported(self._controller.records(), loaded.records)
        self.set_status_message(
            self._apply_merge(merged, summarise_import(merged.counts), "import")
        )

    def _refuse_import(self, detail: str) -> None:
        log.warning("the profile could not be imported: %s", detail)
        self.set_status_message(
            QCoreApplication.translate(_TR_CONTEXT, "Profile not loaded: %1").replace(
                "%1", detail
            )
        )

    def scan_roots(self) -> tuple[Path, ...]:
        """The folders a Rescan walks, or none when there is nothing to rescan.

        An accessor naming the contract rather than exposure of `_rescan`:
        what the settings dialog needs is the list of folders, not the window's
        rescan plumbing (LWSM-1018).
        """
        return self._rescan.roots if self._rescan is not None else ()

    def set_scan_roots(self, roots: Sequence[Path]) -> None:
        """Point future rescans at a new list, without rebuilding the window.

        `RescanContext` is frozen, so this REPLACES it rather than mutating it
        — which is also what keeps the injected `scan`, `now` and `save` seams a
        test supplied.

        A window with no context stays without one. No roots is not the same as
        no way to rescan, and inventing a context here would put an enabled
        Rescan control in front of a window built deliberately without one —
        the rule `_build_menus` already follows.
        """
        if self._rescan is not None:
            self._rescan = replace(self._rescan, roots=tuple(roots))

    def _set_rescan_enabled(self, enabled: bool) -> None:
        """The button and the menu entry are one control with two faces.

        Import rides along, and that is not tidiness (LWSM-1148): a merge
        landing while a rescan is in flight is written by whichever finishes
        last, so the restored user half would be silently dropped by a rescan
        that started before it. Export does not — it only reads.
        """
        if self._rescan_button is not None:
            self._rescan_button.setEnabled(enabled)
        if self._rescan_action is not None:
            self._rescan_action.setEnabled(enabled)
        if self._import_action is not None:
            self._import_action.setEnabled(enabled)

    def _retranslate_strip(self) -> None:
        """The strip's user-visible strings — the filter box's two (LWSM-1040)
        and the Rescan button's label (LWSM-1177).

        Its own method, and set from here rather than at construction, for the
        reason `_retranslate_menus` gives: `LanguageChange` needs one place to
        go. The button was the exception and stayed in its construction
        language: `_set_rescan_enabled` treats it and the menu entry as one
        control with two faces, but only the entry was ever retranslated. Its
        accessible name is derived from this text (`§ O8`), so the announcement
        went stale with the label.

        It cannot be done in `_retranslate_menus` instead: `_build_menus` runs
        before the strip is built, so the button does not exist yet.

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
        if self._rescan_button is not None:
            self._rescan_button.setText(self._rescan_label())

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

    def _visible_rows(self) -> list[ProjectRow]:
        """The rows the filter is currently showing, in the order they appear.

        `isHidden`, not `isVisible`. The question is "did the filter remove
        this row", and `isHidden` answers exactly that — it tracks the flag
        `_apply_filter` sets and nothing else. `isVisible` answers a wider one,
        folding in every ancestor's state, and returns False for every row
        while the window itself is unshown.

        Extracted by LWSM-1156, which needed the same list the number-key
        shortcut already builds. Two copies would be two places for that
        distinction to drift, and it is the kind that looks equivalent until a
        test runs against an unshown window.
        """
        return [row for row in self._ordered_rows() if not row.isHidden()]

    def _focus_first_match(self) -> None:
        """Enter in the filter box moves to the first row still showing.

        LWSM-1156, split out of LWSM-1040 rather than widening it: the app was
        already fully keyboard-operable without this, and what it saves is the
        Tab between typing a filter and reaching what the filter found.

        **An empty result set does nothing** — no focus move, no raise. Enter
        on a filter matching nothing has no row to go to, and moving focus
        somewhere arbitrary would be worse than leaving the caret where the
        user can keep typing.
        """
        shown = self._visible_rows()
        if shown:
            shown[0].setFocus(Qt.FocusReason.ShortcutFocusReason)

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
            # Two independent reasons to be off screen, and the same mechanism
            # for both: a hidden project is a stored preference and the needle
            # is a live one, so neither may resurrect a row the other excluded.
            showable = self._show_hidden or not row.hidden_by_user()
            row.setVisible(showable and row.matches(needle))

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
            shown = self._visible_rows()
            index = key - Qt.Key.Key_1
            if index < len(shown):
                shown[index].setFocus(Qt.FocusReason.ShortcutFocusReason)
                event.accept()
                return
        super().keyPressEvent(event)

    @staticmethod
    def _window_title() -> str:
        """The app name and the running version (LWSM-1186).

        `%1` and `str.replace`, never an f-string, for the reason
        `port_label` states: a translation is data from outside the program,
        and a translator must be able to move the number rather than have it
        welded to the end. Rebuilt on `LanguageChange` like every other
        string, so the version survives a language switch.
        """
        return QCoreApplication.translate(
            _TR_CONTEXT, "Local Web Server Manager %1"
        ).replace("%1", __version__)

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
            self._retranslate_strip()
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

        **All three fields go in on ONE pass, and their line breaks are
        escaped** (LWSM-1181). They were substituted in sequence, so the name
        landed in a template still holding `%2` and `%3` and a directory called
        `evil%2` had the launcher path pasted into its own name. And every one
        of the three comes from someone else's tree, while the headings are
        this dialog's only structure — so a newline in any of them forged a
        second "This will execute:" naming a different launcher, above the real
        one. `re.sub` never rescans what it substituted, and an escaped break
        cannot pass for layout.

        A name holding a literal backslash-n is displayed the same as one
        holding a line break. That is a stated loss: distinguishing them costs
        escaping every backslash in every path, and neither can forge the
        dialog, which is what this is defending.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(
            QCoreApplication.translate(_TR_CONTEXT, "Run this launcher?")
        )
        fields = {
            "%1": project.name,
            "%2": resolved,
            "%3": " ".join(argv),
        }
        box.setText(
            _TRUST_FIELD.sub(
                lambda match: _no_line_breaks(fields[match.group()]),
                QCoreApplication.translate(
                    _TR_CONTEXT,
                    "%1 has not been run from here before.\n\n"
                    "This will execute:\n%2\n\nwith arguments:\n%3",
                ),
            )
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
        url = project_url(view.effective_port)
        chosen = browsers.by_id(self._browsers, view.browser)
        if chosen is None:
            if view.browser is not None:
                # LWSM-1055's third acceptance criterion: an uninstalled browser
                # falls back to the default WITH a visible message. The picker
                # reading "Default browser" is not that message -- it looks
                # identical to a project nobody ever set one for, which is the
                # silent failure the criterion names.
                self.set_status_message(
                    QCoreApplication.translate(
                        _TR_CONTEXT,
                        "%1's chosen browser is not installed - opening in the default",
                    ).replace("%1", view.name)
                )
            # openUrl returns False when the desktop has no handler. Silence
            # here would look identical to a browser that opened behind the
            # window.
            opened = self._open_url(url)
        else:
            # A chosen browser is launched directly, so the desktop's default
            # handler is never consulted. `by_id` returns None for an id whose
            # browser is no longer installed, so reaching here means the entry
            # was on disk when the list was scanned (LWSM-1187).
            try:
                browsers.open_url(chosen, url.toString())
                opened = True
            except browsers.BrowserError as exc:
                log.warning("open %s: %s", path, exc)
                opened = False
        if not opened:
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "Could not open a browser for %1"
                ).replace("%1", path.name)
            )

    def _set_show_hidden(self, showing: bool) -> None:
        """The View menu toggle (LWSM-1185)."""
        self._show_hidden = showing
        self._apply_filter()

    def set_project_hidden(self, path: Path, hidden: bool) -> None:
        """Hide or unhide one project, and remember the choice.

        The record is replaced rather than mutated: `ProjectRecord` is frozen,
        and every other writer here hands the controller a new list.
        """
        records = [
            replace(record, hidden=hidden) if record.path == path else record
            for record in self._controller.records()
        ]
        name = next((r.name for r in records if r.path == path), path.name)
        self.set_status_message(
            self._write_records(
                records,
                QCoreApplication.translate(
                    _TR_CONTEXT, "%1 is hidden" if hidden else "%1 is shown again"
                ).replace("%1", name),
                "hide",
            )
        )

    def set_project_browser(self, path: Path, entry_id: str | None) -> None:
        """Remember which browser Open uses for one project (LWSM-1187).

        `set_project_hidden`'s shape exactly, and through the same
        `_write_records`: the write gate, the `RegistryError` report and the
        `self._load` refresh are the same three rules for the fourth writer as
        for the first three, and LWSM-1166 was that refresh being read from the
        wrong place.

        An empty choice is stored as `None` rather than `""`, so the file has
        one spelling of "no preference" and `browsers.by_id` has one case.
        """
        records = [
            replace(record, browser=entry_id) if record.path == path else record
            for record in self._controller.records()
        ]
        name = next((r.name for r in records if r.path == path), path.name)
        chosen = browsers.by_id(self._browsers, entry_id)
        message = (
            QCoreApplication.translate(_TR_CONTEXT, "%1 opens in %2")
            .replace("%1", name)
            .replace("%2", chosen.name)
            if chosen is not None
            else QCoreApplication.translate(
                _TR_CONTEXT, "%1 opens in the default browser"
            ).replace("%1", name)
        )
        self.set_status_message(self._write_records(records, message, "browser"))

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
        return self._apply_merge(merged, summarise_merge(merged.counts), "rescan")

    def _apply_merge(self, merged: MergeResult, message: str, source: str) -> str:
        """Write a merge and show it, whichever merge produced it.

        Generalised out of `_apply_rescan` by LWSM-1148 rather than copied: the
        write gate, the `RegistryError` handling and the `self._load` refresh
        after a successful write are the same three rules for an import, and a
        second copy of them would be a second place for the refresh to be
        forgotten. Only the leading word and the log prefix differ.
        """
        if self._rescan is None:
            return ""
        for reason in merged.reasons:
            # The full report goes to the log, one record each; the status bar
            # gets the summary. INV-6's bound already applies to the entries.
            log.info("%s: %s", source, reason)

        return self._write_records(merged.records, message, source)

    def _write_records(
        self, records: list[ProjectRecord], message: str, source: str
    ) -> str:
        """Save a new project list and show it, whatever produced it.

        Every writer goes through here — a rescan, an import, and hiding a
        project — because the three rules are the same each time and each is
        one somebody has already got wrong once: the write gate, the
        `RegistryError` report, and the `self._load` refresh on success.
        LWSM-1166 was that refresh being read from the wrong place, and a
        second copy of this would be a second place to make that mistake.
        """
        if self._rescan is None:
            return message
        if self._should_write(records):
            try:
                self._rescan.save(self._rescan.projects_path, records, load=self._load)
            except RegistryError as exc:
                log.warning("the %s could not be saved: %s", source, exc)
                message = (
                    QCoreApplication.translate(_TR_CONTEXT, "%1 — not saved: %2")
                    .replace("%1", message)
                    .replace("%2", str(exc))
                )
            else:
                # The next write, of any kind, compares against what is now on
                # disk. Without this, a first run stays `RegistryMissing` for
                # the life of the session and every later write is
                # unconditional.
                self._load = LoadResult(
                    records=list(records), reasons=[], rows_refused=0
                )

        self._controller.set_records(records)
        return message

    def _should_write(self, records: list[ProjectRecord]) -> bool:
        """Exactly one trigger, plus first run.

        Record **content**, not report entries: three outcomes flag a row while
        leaving every field identical — *missing*, *not re-observed* and
        *duplicate identity* — and none of them writes. A no-op rewrite would
        churn the file's mtime and widen the only window in which a concurrent
        writer can lose an edit, for no gain.

        The comparison is against **the load**, never against the controller's
        in-memory set (LWSM-1166). `_apply_merge` calls `set_records`
        unconditionally, so after a refused write the in-memory set already
        holds the merge — a gate reading it finds no difference next time,
        writes nothing and reports "no changes" while nothing has ever reached
        the disk. `self._load` is refreshed only on the success branch, so it
        is the one value that still says what is actually stored.

        First run is the exception and is not an optimisation: with no file,
        "differs from the loaded one" is vacuous, and on a clean machine whose
        first scan finds **zero** projects both sets are empty, the difference
        test says no, and `projects.json` would never come into existence at
        all — every later run repeating the whole first-run path. A load that
        raised for any other reason is vacuous in the same way, and offering
        the write is safe because `save_projects`' own gate refuses it and the
        user is told why — every time, which is the point.
        """
        if isinstance(self._load, LoadResult):
            return records != self._load.records
        # No registry to write to at all: `build_window` always passes a load
        # beside a rescan context, so this is a hand-built window only.
        return self._load is not None

    def _sync_rows(self) -> None:
        views = self._controller.rows()
        for view in views:
            existing = self._rows.get(view.path)
            if existing is None:
                widget = ProjectRow(view, self._theme, self, self._browsers)
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
                # Bound the same way and for the same reason as the buttons
                # above: a plain closure over `view` drives the LAST project.
                widget.hide_action.triggered.connect(
                    lambda _checked=False, p=path, w=widget: self.set_project_hidden(
                        p, not w.hidden_by_user()
                    )
                )
                # Same binding, same reason. `update_from` blocks this signal
                # while it sets the box from the poll, so reaching here means a
                # person changed it.
                widget.browser_box.currentIndexChanged.connect(
                    lambda _index=0, p=path, w=widget: self.set_project_browser(
                        p, w.browser_box.currentData() or None
                    )
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

    def _screen_area(self) -> Rect | None:
        """The usable area of the screen this window is on, panels excluded."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        room = screen.availableGeometry()
        return Rect(room.x(), room.y(), room.width(), room.height())

    def _screens(self) -> list[Rect]:
        """Every attached screen's usable area, for `clamp_to_screens`.

        `availableGeometry`, not `geometry`, so a remembered position is
        clamped to the area a window can actually occupy rather than to the
        raw display — restoring one under the panel is not much better than
        restoring it off-screen.
        """
        return [
            Rect(room.x(), room.y(), room.width(), room.height())
            for room in (
                screen.availableGeometry() for screen in QApplication.screens()
            )
        ]

    def _place_at(self, target: Rect) -> Rect | None:
        """Ask for `target` — a frame corner and a CLIENT size; `None` if the
        ask could not be made.

        The size is the client's throughout this window, because `resize()` is
        what consumes it and it has to round-trip exactly through
        `closeEvent`. KWin needs a frame size instead, and the conversion is
        `kwin_script`'s: the decoration is not known here at the moment
        placement runs, and it is known there.

        The state directory is resolved here and its failure is caught here,
        because `default_state_dir` raises on a machine with no home directory
        — the LWSM-1116 shape. A window that cannot be positioned is a
        nuisance; one that raises out of `showEvent` is not a window.
        """
        try:
            state_dir = applog.default_state_dir()
        except OSError as exc:
            log.warning("cannot place the window: no state directory (%s)", exc)
            return None
        return self._place(
            target,
            screens=self._screens(),
            pid=os.getpid(),
            move=self.move,
            state_dir=state_dir,
        )

    def centre_on_screen(self) -> None:
        """Put the window back in the middle of its screen (LWSM-1033).

        The same operation as restoring a remembered position, with the target
        computed differently — which is ADR-0007's observation and the reason
        both go through `place_window`.

        Sized from `frameGeometry`, not `geometry`: the title bar and border
        are part of what has to fit, and centring the client area leaves a
        window sitting low by the height of its own decoration.
        """
        area = self._screen_area()
        if area is None:
            return
        # Centred on the FRAME extents, because the title bar and border are
        # part of what has to fit — but sent as the CLIENT size, which is the
        # unit `place_window` takes and the decoration KWin adds back.
        frame = self.frameGeometry()
        spot = centre_in(area, frame.width(), frame.height())
        target = Rect(spot.x, spot.y, self.width(), self.height())
        if self._place_at(target) is None:
            self.set_status_message(
                QCoreApplication.translate(
                    _TR_CONTEXT, "This desktop would not let the window be moved."
                )
            )

    def showEvent(self, event: QShowEvent) -> None:
        """Arm the restore: first EXPOSE, then one event-loop tick.

        Deferred rather than done in `__init__`, because KWin can only move a
        window it already knows about and on Wayland the surface is not
        committed while `showEvent` is still running (ADR-0007). The cost is a
        brief jump from wherever the compositor first put it, which is the
        price of the compositor owning placement — a window that arrives in
        the right place a frame late beats one that never arrives there.

        **ADR-0007 says one tick after the SHOW, and that is measurably too
        early.** Against real KWin on this machine's Plasma 6 Wayland session
        (2026-08-21), a window shown with a remembered position at 305,255
        opened at 1570,793 — the script ran, matched our PID and set
        `frameGeometry`, and the compositor ignored it, which is exactly the
        silent shape the ADR exists to avoid. Measured: a 0 ms delay after
        `show` fails; 50, 150 and 400 ms all work; the first `Expose` ALONE
        still fails; `Expose` plus one tick worked 5 times out of 5. So the
        trigger is a condition rather than a chosen number — the surface has
        been presented, and the compositor has had one turn of our loop to
        finish with it.

        **No test in this suite can see that.** The Wayland tests substitute a
        stand-in for KWin, which honours whatever it is handed whenever it is
        handed it, so they were green against the version that did not work.
        Only running the app under the real compositor found it.
        """
        super().showEvent(event)
        if self._geometry_restored:
            return
        self._geometry_restored = True
        handle = self.windowHandle()
        # Already exposed, or no handle to watch: there is no Expose still to
        # come, so waiting for one would mean never restoring at all.
        if handle is None or handle.isExposed():
            QTimer.singleShot(0, self._restore_geometry)
            return
        handle.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """The other half of `showEvent`: the window's first presentation.

        Watching the `QWindow` rather than this widget, because `Expose` is
        delivered to the handle and never to the `QMainWindow`. The filter is
        removed as soon as it fires, so a window the user hides and reshows is
        not re-placed under them.
        """
        if (
            event.type() == QEvent.Type.Expose
            and watched is self.windowHandle()
            and self.windowHandle().isExposed()
        ):
            watched.removeEventFilter(self)
            QTimer.singleShot(0, self._restore_geometry)
        return super().eventFilter(watched, event)

    def _restore_geometry(self) -> None:
        """Size first, then position — and neither if there is nothing stored.

        **The order is load-bearing, but not for the reason this said.** An
        early version of the KWin script preserved the window's current size by
        reading `c.frameGeometry.width` back as it ran, which raced a `resize()`
        the compositor had not applied yet. The shipped script is HANDED the
        size instead, so that race is not in the code any more;
        `placement.kwin_script` records what each measurement refuted, and the
        constraint that survived — KWin's geometry write is authoritative, so
        the script must carry the size — is stated there rather than here.

        What keeps the order today is LWSM-1172: the placement call below is
        given the window's OWN size rather than the remembered one, and that
        reads correctly only once the bounded resize has happened.

        Whether any ordering hazard remains under a live compositor has not
        been re-measured since the script stopped reading the size back, and a
        green suite is not evidence for anything the compositor owns.

        The size is applied here as well as in `_apply_default_geometry`,
        which is not a duplicate: that method returns early when there are no
        rows, and a user whose project list is empty still closed the window
        at a size they chose.

        A maximised window is restored maximised and not placed. Its position
        is the screen's, so asking KWin for the stored coordinates would
        un-maximise it to honour them — but its normal size is still applied
        first, so that un-maximising later gives back the window they had.
        """
        if self._remembered_size is not None:
            # Bounded, because a size is restored on every platform while
            # placement can be refused — so this is the only guard ADR-0007's
            # "sized larger than the current display" case ever gets.
            self.resize(self._bounded_to_screen(QSize(*self._remembered_size)))
        if self._remembered_maximized:
            self.showMaximized()
            return
        if self._remembered_pos is None:
            return
        # The window's OWN size, not the remembered one: where a size was
        # remembered the resize above has already applied it bounded, and
        # sending the unbounded value would ask KWin for a rectangle the
        # window is not. A session that remembered a position without a size
        # still deserves the position, and this reads correctly there too.
        self._place_at(Rect(*self._remembered_pos, self.width(), self.height()))

    def closeEvent(self, event: QCloseEvent) -> None:
        """Remember where the window was, then let it close.

        `normalGeometry`, never `geometry`: a maximised window's geometry is
        the screen's, and storing that as the normal size gives a window that
        fills the display on the next run without being maximised — which the
        user cannot undo with the maximise button, because it is not maximised.

        **The position stored is the FRAME's corner and the size stored is the
        CLIENT's**, because those are what `move()` and `resize()` consume, and
        a value that does not round-trip through the call that restores it
        drifts by the size of the decoration on every launch. Measured on this
        machine: `move(137, 219)` leaves `geometry()` reporting `(139, 221)`,
        so storing `normalGeometry()`'s corner and restoring it with `move`
        walks the window two pixels down and right each time it is opened.

        `normalGeometry` has no frame counterpart, so the decoration offset is
        measured live off this window and added. While the window is not
        maximised the two agree exactly and the offset is what makes them; it
        is only an estimate for the maximised case, where the frame is the
        screen's and the normal frame no longer exists to be measured.

        **Under Wayland the position is not stored at all**, and that is the
        one thing this method cannot work around. A client there is never told
        where it is: measured 2026-08-21, KWin reported this window at 640,480
        while Qt reported 0,0 — and 0,0 is a real position, so it would be
        written as though it were true and reopen the window in the corner.
        The size is recorded normally, and the stored position is left exactly
        as it was rather than overwritten with a fiction.
        """
        normal = self.normalGeometry()
        offset = self.pos() - self.geometry().topLeft()
        remembered = (
            Rect(
                normal.x() + offset.x(),
                normal.y() + offset.y(),
                normal.width(),
                normal.height(),
            )
            if normal.isValid()
            else None
        )
        if self._save_geometry is not None:
            try:
                self._save_geometry(
                    remembered,
                    self.isMaximized(),
                    placement.position_is_readable(),
                )
            except (ConfigFileError, OSError) as exc:
                # Logged, not shown: the window is going away, so a status bar
                # message has nobody left to read it.
                log.warning("could not remember the window geometry: %s", exc)
        super().closeEvent(event)

    def _apply_default_geometry(self) -> None:
        """Open big enough to read (LWSM-1149), or at the remembered size.

        A first run has nothing remembered, so this is the only impression a
        new user gets, and Qt's own default was ~790x520 with the list crushed
        against the window chrome. Where LWSM-1033 DID remember a size, that
        size wins over the measured one and only the minimum is computed here
        — a floor still has to be applied, or a remembered size from a
        narrower font clips a column.

        **That preference decides something only when this runs AFTER
        `_restore_geometry`**, which is the reverse of the usual order:
        `_sync_rows` runs inside `__init__`, so a window built with records
        already sizes itself before it is ever shown. The order flips when the
        rows arrive later — an empty or unreadable `projects.json`, or a
        rescan finding the user's first project — and there the measured size
        would otherwise land on top of the one the user chose. A mutation
        proved this branch unobserved on 2026-08-21;
        `test_rows_arriving_after_the_restore_do_not_undo_the_remembered_size`
        is what reaches it.

        The remembered POSITION is not applied here. It is `_restore_geometry`'s,
        which runs off the first show rather than off the first scan.

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

        want = (
            QSize(*self._remembered_size)
            if self._remembered_size is not None
            else QSize(
                width, chrome + min(len(rows), DEFAULT_VISIBLE_ROWS) * row_height
            )
        )
        # The columns are fixed-width, so there is no narrower window in which
        # they do not collide — the floor is the content itself, and only the
        # height is negotiable.
        floor = QSize(width, chrome + MIN_VISIBLE_ROWS * row_height)

        self.setMinimumSize(self._bounded_to_screen(floor))
        self.resize(self._bounded_to_screen(want))

    def _bounded_to_screen(self, size: QSize) -> QSize:
        """`size`, never bigger than the screen this window is on.

        ADR-0007 requires a restored geometry to be validated against the
        CURRENT screens and names "sized larger than the current display" as
        the case: `"width": 3800` recorded on a 4K monitor otherwise opens off
        the edge of a 1920x1080 laptop, where the corner that would drag it
        back is unreachable.

        **One rule, called from both places that apply a remembered size.**
        `_restore_geometry` discarded the bound entirely and ran last, so the
        cap computed here was overwritten on the path where rows exist and
        never computed at all on the path where they do not (measured
        2026-08-25: three times the screen, on both). Two copies of the
        fraction is how the same stored file starts giving two windows.

        No screen at all is the headless case; there is nothing to bound
        against and the asked-for size stands.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return size
        room = screen.availableGeometry()
        return size.boundedTo(
            QSize(
                int(room.width() * SCREEN_FRACTION),
                int(room.height() * SCREEN_FRACTION),
            )
        )

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
