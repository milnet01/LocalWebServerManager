"""The "What's using a port?" window (LWSM-1041).

UI layer — imports QtWidgets, so no core module may import it back
(`docs/standards/coding-overrides.md § O1`, enforced by `tests/test_layering.py`).

**It owns no answer.** It is handed `lookup`, which is
`ProjectController.port_lookup`, and only parses the port and shows the
sentence that comes back. That keeps the wording testable without a display.

Not modal: it is a question asked while looking at the list, so the list stays
usable behind it.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent, QIntValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from lwsm.mainwindow import MIN_TARGET_PX

# Every user-visible string here goes through the one context
# "PortLookupDialog", repeated as a literal because `pyside6-lupdate` skips a
# call whose context is not one — see mainwindow.py's note (LWSM-1304).

MIN_PORT = 1
MAX_PORT = 65535


class PortLookupDialog(QDialog):
    """A port box and the answer under it."""

    def __init__(
        self, *, lookup: Callable[[int], str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._lookup = lookup

        self._port = QLineEdit()
        self._port.setValidator(QIntValidator(MIN_PORT, MAX_PORT, self._port))
        self._port.setMinimumHeight(MIN_TARGET_PX)
        # Answered as the user types, so the box needs no button of its own.
        self._port.textChanged.connect(self._answer)
        # Enter asks again — the snapshot moves on every poll — and reads the
        # answer out. Typing alone does not announce, or a four-digit port
        # would be read out four times.
        self._port.returnPressed.connect(self._announce)

        self._port_label = QLabel()
        self._port_label.setBuddy(self._port)

        self._result = QLabel()
        # PlainText: the answer interpolates a program path and a project name.
        self._result.setTextFormat(Qt.TextFormat.PlainText)
        self._result.setWordWrap(True)
        # Selectable, so a PID or a path can be copied out.
        self._result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close = self._buttons.button(QDialogButtonBox.StandardButton.Close)
        close.setMinimumHeight(MIN_TARGET_PX)
        close.setMinimumWidth(MIN_TARGET_PX)
        # Enter belongs to the port box, so Close must not be the default.
        close.setAutoDefault(False)
        self._buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow(self._port_label, self._port)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._result)
        layout.addWidget(self._buttons)

        self._retranslate()
        self._answer()

    def _retranslate(self) -> None:
        self.setWindowTitle(
            QCoreApplication.translate("PortLookupDialog", "What's using a port?")
        )
        self._port_label.setText(
            QCoreApplication.translate("PortLookupDialog", "&Port:")
        )

    def _answer(self) -> None:
        """Show what holds the typed port, or what to type."""
        # The validator accepts the locale's group separator ("1,080"), which
        # int() refuses, so the number is read back through the same locale.
        port, ok = self._port.validator().locale().toInt(self._port.text())
        if ok and self._port.hasAcceptableInput():
            text = self._lookup(port)
        else:
            text = QCoreApplication.translate(
                "PortLookupDialog", "Type a port number from 1 to 65535."
            )
        self._result.setText(text)
        # The label is not focusable, so its text reaches a screen reader as
        # the box's description.
        self._port.setAccessibleDescription(text)

    def _announce(self) -> None:
        self._answer()
        QAccessible.updateAccessibility(
            QAccessibleAnnouncementEvent(self, self._result.text())
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
            # The hint under an empty box is translated too.
            self._answer()
        super().changeEvent(event)
