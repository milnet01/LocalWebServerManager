"""The "What's using a port?" window (LWSM-1041).

The answer's wording is the controller's and is tested in
`test_controller.py`; this file tests the window: what it asks, and what it
shows.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QPushButton

from lwsm.mainwindow import MIN_TARGET_PX
from lwsm.portlookup import PortLookupDialog

pytestmark = pytest.mark.gui


def build(qtbot, asked: list[int]) -> PortLookupDialog:
    def lookup(port: int) -> str:
        asked.append(port)
        return f"answer for {port}"

    dialog = PortLookupDialog(lookup=lookup)
    qtbot.addWidget(dialog)
    return dialog


def test_a_typed_port_shows_the_lookups_answer(qtbot) -> None:
    asked: list[int] = []
    dialog = build(qtbot, asked)

    dialog._port.setText("5005")

    assert asked[-1] == 5005
    assert dialog._result.text() == "answer for 5005"
    # The label is not focusable, so a screen reader hears it through the box.
    assert dialog._port.accessibleDescription() == "answer for 5005"


@pytest.mark.parametrize("text", ["", "0", "65536", "abc"])
def test_a_port_out_of_range_asks_for_one_instead(qtbot, text: str) -> None:
    """Never asks the controller about a port that cannot exist."""
    asked: list[int] = []
    dialog = build(qtbot, asked)

    dialog._port.setText(text)

    assert asked == []
    # The range is written as the locale writes numbers ("65,535" in English).
    assert QLocale().toString(65535) in dialog._result.text()
    # The hint is not an answer, so there is nothing to copy (LWSM-1457).
    assert not dialog._copy.isEnabled()


@pytest.mark.parametrize("text", ["1,080", "+80"])
def test_a_port_the_validator_accepts_is_looked_up(qtbot, text: str) -> None:
    """QIntValidator accepts a group separator and a sign, which int() did
    not: "1,080" raised ValueError out of the textChanged slot."""
    asked: list[int] = []
    dialog = build(qtbot, asked)

    dialog._port.setText(text)

    assert asked[-1] == int(text.replace(",", ""))


def test_enter_asks_again(qtbot) -> None:
    """The snapshot moves on every poll, so Enter re-asks rather than
    repeating the answer it already has."""
    asked: list[int] = []
    dialog = build(qtbot, asked)
    dialog._port.setText("8080")

    dialog._port.returnPressed.emit()

    assert asked == [8080, 8080]


def test_the_controls_clear_the_target_floor(qtbot) -> None:
    """`design-accessibility.md`'s 24x24 floor, as the settings dialog has it."""
    dialog = build(qtbot, [])
    close = dialog._buttons.button(QDialogButtonBox.StandardButton.Close)

    assert dialog._port.minimumHeight() >= MIN_TARGET_PX
    assert close.minimumHeight() >= MIN_TARGET_PX
    assert close.minimumWidth() >= MIN_TARGET_PX
    assert dialog._copy.minimumHeight() >= MIN_TARGET_PX
    assert dialog._copy.minimumWidth() >= MIN_TARGET_PX


def test_tab_reaches_a_button_that_copies_the_answer(qtbot) -> None:
    """LWSM-1457: the answer label takes click focus only, so a keyboard
    user could not copy a PID or a path. A Copy button beside Close is the
    keyboard's route; the label stays unfocusable, so the screen-reader route
    through the box's description is unchanged."""
    dialog = build(qtbot, [])
    dialog.show()
    with qtbot.waitActive(dialog):
        dialog.activateWindow()
    dialog._port.setFocus()
    dialog._port.setText("5005")
    QApplication.clipboard().clear()

    qtbot.keyClick(dialog._port, Qt.Key.Key_Tab)
    copy = QApplication.focusWidget()
    assert isinstance(copy, QPushButton), "Tab from the port box reached no button"
    qtbot.keyClick(copy, Qt.Key.Key_Space)

    assert QApplication.clipboard().text() == "answer for 5005"
    # Enter still belongs to the port box.
    assert not copy.autoDefault()
    assert dialog._result.focusPolicy() == Qt.FocusPolicy.ClickFocus


def test_the_answer_label_is_not_a_tab_stop(qtbot) -> None:
    """LWSM-1572 row 14.7, measured: `TextSelectableByKeyboard` still leaves a
    QLabel at ClickFocus, so Tab skips it. The keyboard's way to the answer is
    the Copy button, and a magnifier following focus is not sent to a label."""
    dialog = build(qtbot, [])

    assert dialog._result.focusPolicy() == Qt.FocusPolicy.ClickFocus


def test_a_reopened_window_asks_again(qtbot) -> None:
    """LWSM-1572: the snapshot moves on every poll, so the sentence a closed
    window kept may be false by the time it is shown again."""
    asked: list[int] = []
    dialog = build(qtbot, asked)
    dialog._port.setText("8080")
    dialog.hide()
    asked.clear()

    dialog.show()

    assert asked == [8080]


def test_the_hint_writes_the_range_in_the_locales_digits(qtbot) -> None:
    """LWSM-1572: the range comes from MIN_PORT and MAX_PORT through the locale,
    as the sibling dialogs write their numbers."""
    from PySide6.QtCore import QLocale

    from lwsm.portlookup import MAX_PORT, MIN_PORT

    previous = QLocale()
    QLocale.setDefault(QLocale("ar_EG"))
    try:
        dialog = build(qtbot, [])
        text = dialog._result.text()
        want_min = QLocale().toString(MIN_PORT)
        want_max = QLocale().toString(MAX_PORT)
    finally:
        QLocale.setDefault(previous)

    assert want_max != str(MAX_PORT), "the locale does not change digits"
    assert want_min in text and want_max in text, text
    assert str(MAX_PORT) not in text, text
