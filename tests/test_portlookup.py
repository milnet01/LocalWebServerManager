"""The "What's using a port?" window (LWSM-1041).

The answer's wording is the controller's and is tested in
`test_controller.py`; this file tests the window: what it asks, and what it
shows.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialogButtonBox

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
    assert "1 to 65535" in dialog._result.text()


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
