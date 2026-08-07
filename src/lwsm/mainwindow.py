"""The window: one row per project, each stating its status as a word.

UI layer. Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`.

Two rules this file exists to obey. `docs/standards/coding.md § O7`: no colour
literal, no font family, no pixel constant — colours come from `Theme` tokens
and sizes from the text metric. `§ O8`: every row lands with an accessible
name, keyboard reachability, its state as text, and a layout that reflows.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QRectF, Qt
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from lwsm.controller import ProjectController, ProjectStatus, RowView
from lwsm.theme import Theme

# Decorative only. One of the three signals design.md § Accessibility requires,
# and excluded from the accessible name — a screen reader announcing "black
# circle, running" is noise wearing the costume of redundancy.
STATE_GLYPHS = {
    ProjectStatus.RUNNING: "●",
    ProjectStatus.STOPPED: "○",
    ProjectStatus.UNKNOWN: "?",
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

    def update_from(self, row: RowView) -> None:
        if row == self._view:
            # `_sync_rows` calls this on EVERY row on every signal, and only
            # `QLabel::setText` short-circuits — `setStyleSheet` and
            # `setAccessibleName` do not, and the announcement below certainly
            # does not. Without this guard the announcement turns a
            # once-a-second no-op into a once-a-second re-announcement of every
            # unchanged row: the failure INV-13 exists to prevent, arriving by
            # another route. `RowView` is frozen, so the comparison is free.
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
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._theme = theme
        self.setWindowTitle(self.tr("Local Web Server Manager"))
        self.setPalette(theme.to_palette())
        # Set once for the whole window; rows carry a state property the rules
        # in it select on.
        self.setStyleSheet(theme.style_sheet())

        central = QWidget(self)
        self._rows_layout = QVBoxLayout(central)
        self._rows_layout.addStretch(1)
        self.setCentralWidget(central)

        self._rows: dict[Path, ProjectRow] = {}
        self._sync_rows()
        controller.projects_changed.connect(self._sync_rows)

        if notices:
            first = notices[0]
            extra = f" (+{len(notices) - 1} more)" if len(notices) > 1 else ""
            self.set_status_message(f"{first}{extra}")

    def set_status_message(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _sync_rows(self) -> None:
        views = self._controller.rows()
        for view in views:
            existing = self._rows.get(view.path)
            if existing is None:
                widget = ProjectRow(view, self._theme, self)
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
            self._rows_layout.removeWidget(widget)
            widget.deleteLater()
