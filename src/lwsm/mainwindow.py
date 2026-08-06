"""The window: one row per project, each stating its status as a word.

UI layer. Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`.

Two rules this file exists to obey. `docs/standards/coding.md § O7`: no colour
literal, no font family, no pixel constant — colours come from `Theme` tokens
and sizes from the text metric. `§ O8`: every row lands with an accessible
name, keyboard reachability, its state as text, and a layout that reflows.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
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


def port_text(effective_port: int | None) -> str:
    """The word and the number, never a bare number.

    design.md § Accessibility gives the announcement as "…, port 5005"; a bare
    number leaves a listener with something unlabelled.
    """
    return f"port {effective_port}" if effective_port is not None else "no port"


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
        self._glyph = QLabel(self)
        self._glyph.setTextFormat(Qt.TextFormat.PlainText)
        # Excluded from the accessible name; also hidden from the AT tree so a
        # screen reader walking children does not find it either.
        self._glyph.setAccessibleName("")
        self._glyph.setAccessibleDescription("")

        self._state = QLabel(self)
        self._name = QLabel(self)
        self._port = QLabel(self)
        for label in (self._state, self._name, self._port):
            # PlainText explicitly: Qt's default AutoText sniffs for rich text,
            # so a project named with markup would otherwise be rendered as it.
            label.setTextFormat(Qt.TextFormat.PlainText)

        # State cell first — design.md § Accessibility: "the state word is
        # first in the row". Visual order is tab order.
        layout.addWidget(self._glyph)
        layout.addWidget(self._state)
        layout.addWidget(self._name, stretch=1)
        layout.addWidget(self._port)

        # Sized from the text metric, never a pixel constant, so the row
        # reflows when the text grows.
        self._state.setMinimumWidth(self.fontMetrics().horizontalAdvance("stopped_"))
        self._port.setMinimumWidth(self.fontMetrics().horizontalAdvance("no port_"))

        self.update_from(row)

    def focus_ring_width(self) -> int:
        """Derived from the text metric, never a pixel constant (`§ O7`).

        A fixed width would thin to a hairline under LWSM-1032's 200 % text-size
        control, which is precisely the setting the users who depend on the ring
        are most likely to be running.
        """
        return max(1, round(self.fontMetrics().height() / 8))

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the focus ring `QFrame` does not.

        `QFrame` renders only its frame and `StyledPanel` never consults
        `State_HasFocus`, so before this the focused and unfocused renders were
        byte-identical and Tab moved an invisible caret (LWSM-1070).
        `coding.md § O8` requires a visible focus ring, `design.md
        § Accessibility` calls it the thing a magnifier user's "where am I?"
        depends on entirely, and WCAG 2.4.7 requires it outright.
        """
        super().paintEvent(event)
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
        self._glyph.setText(STATE_GLYPHS[row.status])
        self._state.setText(str(row.status))
        self._name.setText(row.name)
        self._port.setText(port_text(row.effective_port))

        token = self._theme.state_token(row.status)
        self._glyph.setStyleSheet(f"color: {token};")
        self._state.setStyleSheet(f"color: {token};")

        # Built from the rendered cell strings, glyph excluded, so there is no
        # accessibility-only string that can drift from what is on screen.
        self.setAccessibleName(
            f"{self._state.text()}, {self._name.text()}, {self._port.text()}"
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
        self.setWindowTitle("Local Web Server Manager")
        self.setPalette(theme.to_palette())

        central = QWidget(self)
        self._rows_layout = QVBoxLayout(central)
        self._rows_layout.addStretch(1)
        self.setCentralWidget(central)

        self._rows: dict[object, ProjectRow] = {}
        self._sync_rows()
        controller.projects_changed.connect(self._sync_rows)

        if notices:
            first = notices[0]
            extra = f" (+{len(notices) - 1} more)" if len(notices) > 1 else ""
            self.set_status_message(f"{first}{extra}")

    def set_status_message(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _sync_rows(self) -> None:
        for view in self._controller.rows():
            existing = self._rows.get(view.path)
            if existing is None:
                widget = ProjectRow(view, self._theme, self)
                self._rows[view.path] = widget
                # Before the trailing stretch, so rows stay top-aligned.
                self._rows_layout.insertWidget(self._rows_layout.count() - 1, widget)
            else:
                existing.update_from(view)
