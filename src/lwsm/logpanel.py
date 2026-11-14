"""The live log panel: one project's output, inside the main window (LWSM-1015).

UI layer — imports QtWidgets, so no core module may import it back
(`docs/standards/coding-overrides.md § O1`). It owns no reading: `LogFeed`
(`logbuffer.py`, core) follows the file or the journal and hands it lines on
the GUI thread.

**In the window, under the list, not a window of its own.** Under Wayland an
application cannot place a window it opens, so a separate log window lands
wherever the compositor puts it and a magnifier user has to go looking for
it — the reason `design-accessibility.md` parents every confirmation to the
window. Here the output is one pan down from the row it belongs to, and the
text-size control reaches it with no code of its own.

**Plain text only** (LWSM-1049): a `QPlainTextEdit`, never a widget that can
render rich text, since Qt's auto-detected rich text loads local resources and
a server's output is untrusted.

**It follows new output unless the user has scrolled up**, and says which in
words (`§ O8` clause 3): scrolling back to read is never interrupted, and
reaching the bottom again — by scrolling, or Ctrl+End — resumes following.

**It finds the error for the user** (LWSM-1036): *Jump to last error* selects
the last line `ErrorMatcher` (core) calls an error, scrolls to it, moves focus
there so the lens follows, and says the line aloud; *Errors only* hides the
rest. Scrolling a wall of output under a magnifier is slow and easy to lose
your place in.

Every user-visible string goes through the one context "LogPanel", repeated
as a literal because `pyside6-lupdate` skips a call whose context is not one
(LWSM-1304).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import (
    QAccessible,
    QAccessibleAnnouncementEvent,
    QKeyEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lwsm.configfile import display_text
from lwsm.logbuffer import (
    BAD_UNIT,
    JOURNAL_ENDED,
    JOURNAL_FAILED,
    MAX_LINES,
    NO_JOURNAL,
    ErrorMatcher,
    LogFeed,
    LogSource,
)

# The fewest lines the view shows when it opens, and how many it asks for.
# Counts of lines, never pixels (`§ O7`): the height follows the font.
MIN_VISIBLE_LINES = 6
VISIBLE_LINES = 12

# Within this many pixels of the bottom still counts as "at the bottom", so a
# wrapped final line a pixel short of the maximum does not read as scrolled up.
_BOTTOM_SLACK = 2


def _named(template: str, name: str) -> str:
    """`%1` filled in one pass, so a name holding `%1` cannot inject."""
    return template.replace("%1", name)


def _announce(widget: QWidget, text: str) -> None:
    """Say `text` to a screen reader now, whatever has focus. A seam for tests."""
    QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(widget, text))


class LogPanel(QFrame):
    """A heading, a status line and the output, with a Close button.

    `closed` fires when the user closes it, so the window can return focus to
    the row the output belongs to.
    """

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, *, min_target: int = 24) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.feed: LogFeed | None = None
        self._name = ""
        self._source = LogSource()
        self._failure = ""
        self._following = True
        self._matcher = ErrorMatcher()
        # What the last jump found, shown in the status line until the user
        # goes back to following or opens another project.
        self._notice = ""

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        layout.addLayout(header)
        # PlainText for the reason every label here is: the heading carries a
        # project's own name, and AutoText would render its markup.
        self.title = QLabel(self)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        header.addWidget(self.title, 1)
        self.close_button = QPushButton(self)
        self.close_button.setMinimumSize(min_target, min_target)
        self.close_button.clicked.connect(self.close_panel)
        header.addWidget(self.close_button)

        # Under the heading rather than beside it: the heading wraps a long
        # project name, and three buttons beside it would not fit one lens.
        tools = QHBoxLayout()
        layout.addLayout(tools)
        self.jump_button = QPushButton(self)
        self.jump_button.setMinimumSize(min_target, min_target)
        self.jump_button.clicked.connect(self.jump_to_last_error)
        tools.addWidget(self.jump_button)
        self.errors_only = QCheckBox(self)
        self.errors_only.setMinimumSize(min_target, min_target)
        self.errors_only.toggled.connect(self._redraw)
        tools.addWidget(self.errors_only)
        tools.addStretch(1)

        self.status = QLabel(self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.view = QPlainTextEdit(self)
        self.view.setReadOnly(True)
        # Selectable by keyboard as well as mouse, so a line can be copied
        # without a pointer. Read-only already rules out editing it.
        self.view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        # Wrapped, never scrolled sideways: a magnifier user panning a long
        # line loses the line they were on.
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # The widget's own copy of the ring's bound, so the two agree.
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.view.installEventFilter(self)
        layout.addWidget(self.view, 1)
        self._apply_text_metrics()
        self.hide()

    # -- what it shows -------------------------------------------------------

    def open_for(self, name: str, source: LogSource) -> None:
        """Show `name`'s output from `source`, replacing whatever was shown."""
        self._stop_feed()
        self._name = name
        self._source = source
        self._failure = ""
        self._notice = ""
        self._following = True
        self.view.clear()
        self._retranslate()
        if source.file is not None or source.unit is not None:
            feed = LogFeed(source, self)
            feed.lines_added.connect(self.append_lines)
            feed.failed.connect(self._on_failed)
            self.feed = feed
            feed.start()
        self.show()

    def set_output_unavailable(self, unavailable: bool) -> None:
        """The row's state moved on: a foreign server stopped, or one started."""
        if unavailable != self._source.output_unavailable:
            self._source = LogSource(
                file=self._source.file,
                unit=self._source.unit,
                output_unavailable=unavailable,
            )
            self._show_status()

    def set_error_markers(self, markers: tuple[str, ...]) -> None:
        """The lines that count as errors, from Preferences (LWSM-1036)."""
        self._matcher = ErrorMatcher(markers)
        if self.errors_only.isChecked():
            self._redraw()

    def error_markers(self) -> tuple[str, ...]:
        return self._matcher.markers

    def append_lines(self, lines: list[str]) -> None:
        """Add lines at the end; keep the reader's place unless at the bottom."""
        if self.errors_only.isChecked():
            lines = [line for line in lines if self._matcher.matches(line)]
            if not lines:
                return
        bar = self.view.verticalScrollBar()
        following = self._following
        document = self.view.document()
        # The reader's place is held as the block at the top of the view and
        # how many of its wrapped lines are scrolled past, not as the bar's
        # value: once the view is full every append trims blocks from the
        # top, and the value, a count of lines from the top, would then point
        # further down by what was trimmed (LWSM-1516).
        held = bar.value()
        top = document.findBlockByLineNumber(held)
        top_number = top.blockNumber()
        into_top = held - top.firstLineNumber()
        before = document.blockCount()
        for line in lines:
            self.view.appendPlainText(line)
        if following:
            bar.setValue(bar.maximum())
            return
        trimmed = before + len(lines) - document.blockCount()
        top = document.findBlockByNumber(top_number - trimmed)
        bar.setValue(top.firstLineNumber() + into_top if top.isValid() else 0)

    def jump_to_last_error(self) -> None:
        """Select the last error line, show it, focus it and say it.

        Focus goes to the output because a magnifier follows focus, so the
        lens lands on the line; the announcement is the line itself, so a
        screen reader user hears what went wrong without reading for it.
        A jump that scrolls away from the bottom pauses following, as a
        reader's own scroll does, so new output cannot pull the line away.
        """
        block = self.view.document().lastBlock()
        while block.isValid() and not self._matcher.matches(block.text()):
            block = block.previous()
        if not block.isValid():
            self._notice = QCoreApplication.translate(
                "LogPanel", "No error lines in this output."
            )
            self._show_status()
            _announce(self.view, self._notice)
            return
        cursor = QTextCursor(block)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor
        )
        self.view.setTextCursor(cursor)
        self.view.centerCursor()
        self._notice = _named(
            QCoreApplication.translate("LogPanel", "Last error: %1"), block.text()
        )
        self._show_status()
        self.view.setFocus(Qt.FocusReason.OtherFocusReason)
        _announce(self.view, self._notice)

    def _redraw(self) -> None:
        """Show the whole ring again, or only its error lines."""
        lines = (
            self.feed.buffer.lines()
            if self.feed is not None
            else self.view.toPlainText().splitlines()
        )
        self._notice = ""
        self._following = True
        self.view.clear()
        self._apply_placeholder()
        self.append_lines(lines)
        self._show_status()

    def close_panel(self) -> None:
        self._stop_feed()
        self.hide()
        self.closed.emit()

    def shutdown(self) -> None:
        """Stop the follower without announcing a close; the window is going."""
        self._stop_feed()

    def _stop_feed(self) -> None:
        feed, self.feed = self.feed, None
        if feed is not None:
            feed.stop()
            feed.deleteLater()

    # -- status ----------------------------------------------------------

    def _on_scrolled(self, value: int) -> None:
        bar = self.view.verticalScrollBar()
        following = value >= bar.maximum() - _BOTTOM_SLACK
        if following != self._following:
            self._following = following
            if following:
                self._notice = ""
            self._show_status()

    def _on_failed(self, reason: str, detail: str) -> None:
        detail = display_text(detail)
        if reason == NO_JOURNAL:
            self._failure = QCoreApplication.translate(
                "LogPanel",
                "The system journal cannot be read here, so this service's "
                "output cannot be shown.",
            )
        elif reason == BAD_UNIT:
            self._failure = QCoreApplication.translate(
                "LogPanel",
                "%1 is not a valid unit name, so its output cannot be shown.",
            ).replace("%1", detail)
        elif reason == JOURNAL_FAILED:
            self._failure = QCoreApplication.translate(
                "LogPanel", "The journal reader failed: %1"
            ).replace("%1", detail)
        elif reason == JOURNAL_ENDED:
            self._failure = QCoreApplication.translate(
                "LogPanel", "The journal reader stopped (exit %1)."
            ).replace("%1", detail)
        else:
            self._failure = QCoreApplication.translate(
                "LogPanel", "The log file cannot be read: %1"
            ).replace("%1", detail)
        self._show_status()
        QAccessible.updateAccessibility(
            QAccessibleAnnouncementEvent(self.view, self._failure)
        )

    def _show_status(self) -> None:
        source = self._source
        if self._failure:
            text = self._failure
        elif source.file is None and source.unit is None:
            text = QCoreApplication.translate(
                "LogPanel", "There is no output to show for this project."
            )
        elif source.output_unavailable:
            text = QCoreApplication.translate(
                "LogPanel",
                "This server was not started by this app, so its output is "
                "not available here. Anything below is from earlier runs this "
                "app started.",
            )
        elif self._following:
            text = QCoreApplication.translate("LogPanel", "Following new output.")
        else:
            text = QCoreApplication.translate(
                "LogPanel",
                "Paused while you read earlier output. Press Ctrl+End to "
                "follow new output again.",
            )
        if self._notice and not self._failure:
            text = f"{self._notice} {text}"
        if self.errors_only.isChecked():
            only = QCoreApplication.translate(
                "LogPanel", "Showing only the lines that look like errors."
            )
            text = f"{text} {only}"
        self.status.setText(text)
        # Read out when the output takes focus, so the state is heard as well
        # as seen (`§ O8` clause 3).
        self.view.setAccessibleDescription(text)

    # -- words and sizes ---------------------------------------------------

    def _retranslate(self) -> None:
        name = self._name
        self.title.setText(
            _named(QCoreApplication.translate("LogPanel", "Output of %1"), name)
        )
        self.view.setAccessibleName(
            _named(QCoreApplication.translate("LogPanel", "Output of %1"), name)
        )
        self.close_button.setText(QCoreApplication.translate("LogPanel", "Close"))
        self.close_button.setAccessibleName(
            _named(
                QCoreApplication.translate("LogPanel", "Close the output of %1"), name
            )
        )
        self.jump_button.setText(
            QCoreApplication.translate("LogPanel", "Jump to last &error")
        )
        self.jump_button.setAccessibleName(
            _named(
                QCoreApplication.translate(
                    "LogPanel", "Jump to the last error in the output of %1"
                ),
                name,
            )
        )
        self.errors_only.setText(QCoreApplication.translate("LogPanel", "Errors &only"))
        self.errors_only.setAccessibleDescription(
            QCoreApplication.translate(
                "LogPanel", "Hide every line that does not look like an error."
            )
        )
        self._apply_placeholder()
        self._show_status()

    def _apply_placeholder(self) -> None:
        self.view.setPlaceholderText(
            QCoreApplication.translate("LogPanel", "No error lines yet.")
            if self.errors_only.isChecked()
            else QCoreApplication.translate("LogPanel", "No output yet.")
        )

    def _apply_text_metrics(self) -> None:
        lines = self.view.fontMetrics().lineSpacing()
        self.view.setMinimumHeight(MIN_VISIBLE_LINES * lines)

    def preferred_view_height(self) -> int:
        """What the window adds to show the output comfortably."""
        return VISIBLE_LINES * self.view.fontMetrics().lineSpacing()

    def changeEvent(self, event: QEvent) -> None:
        kind = event.type()
        if kind == QEvent.Type.LanguageChange:
            self._retranslate()
        elif kind == QEvent.Type.FontChange:
            self._apply_text_metrics()
        super().changeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Escape in the output closes the panel and goes back to the row.

        Filtered on the view rather than handled by the window: the window's
        Escape clears the filter box, and a read-only text view lets Escape
        through to it.
        """
        if (
            watched is self.view
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
        ):
            self.close_panel()
            return True
        return super().eventFilter(watched, event)
