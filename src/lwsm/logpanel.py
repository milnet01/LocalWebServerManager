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

Every user-visible string goes through the one context "LogPanel", repeated
as a literal because `pyside6-lupdate` skips a call whose context is not one
(LWSM-1304).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lwsm.logbuffer import (
    JOURNAL_ENDED,
    MAX_LINES,
    NO_JOURNAL,
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

    def append_lines(self, lines: list[str]) -> None:
        """Add lines at the end; keep the reader's place unless at the bottom."""
        bar = self.view.verticalScrollBar()
        following = self._following
        held = bar.value()
        for line in lines:
            self.view.appendPlainText(line)
        if following:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(held)

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
            self._show_status()

    def _on_failed(self, reason: str, detail: str) -> None:
        if reason == NO_JOURNAL:
            self._failure = QCoreApplication.translate(
                "LogPanel",
                "The system journal cannot be read here, so this service's "
                "output cannot be shown.",
            )
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
        self.view.setPlaceholderText(
            QCoreApplication.translate("LogPanel", "No output yet.")
        )
        self._show_status()

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
