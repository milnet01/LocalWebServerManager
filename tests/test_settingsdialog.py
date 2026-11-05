"""LWSM-1018 — the Preferences dialog.

The dialog owns no I/O: it is handed values and returns values, and `__main__`
reads and writes the two files. So every test here is about what the widgets
do, and the round-trip through disk is `test_main.py`'s.

**`choose_directory` is injected in every test.** A real
`QFileDialog.getExistingDirectory()` blocks the event loop with nothing to
click it, which is a hang rather than a failure — the same reason
`MainWindow._confirm` is injected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lwsm.mainwindow import MIN_TARGET_PX
from lwsm.settings import (
    DEFAULT_ERROR_MARKERS,
    MAX_LOG_MAX_MIB,
    MAX_POLL_INTERVAL_MS,
    MIN_LOG_MAX_MIB,
    MIN_POLL_INTERVAL_MS,
)
from lwsm.settingsdialog import SettingsDialog, keyboard_focus_order

pytestmark = pytest.mark.gui


def build(
    qtbot, roots=(), poll=1000, log=5, chooser=None, shortcuts=True, markers=None
) -> SettingsDialog:
    dialog = SettingsDialog(
        roots=[Path(root) for root in roots],
        poll_interval_ms=poll,
        log_max_mib=log,
        single_key_shortcuts=shortcuts,
        error_markers=markers if markers is not None else DEFAULT_ERROR_MARKERS,
        choose_directory=chooser if chooser is not None else (lambda: None),
    )
    qtbot.addWidget(dialog)
    return dialog


@pytest.mark.parametrize("base_point_size", [None, 6.0])
def test_every_control_in_the_dialog_clears_the_target_floor(
    qtbot, base_point_size
) -> None:
    """`design-accessibility.md` puts a 24x24 floor under every clickable
    target, and only Add and Remove had one — the two spinboxes and the Ok and
    Cancel buttons had none (LWSM-1206).

    Parametrised over the system font for LWSM-1032's reason, which is the
    same defect one dialog along: a control's height comes from the style,
    which derives it from the font, so this machine's default cleared the
    floor by a single pixel while the CI runner's smaller default did not.
    The ambient case cannot see that; 6 pt fails on any build with no explicit
    floor, whatever machine it runs on.

    The application font is restored by conftest's autouse
    `_restore_application_appearance`, so nothing here has to undo it.

    Ok and Cancel are asked individually and never through the
    `QDialogButtonBox` holding them. Its own geometry is the container's, and
    `keyboard_focus_order` already records the sibling trap: the box's own
    focusPolicy is NoFocus while the buttons inside it are focusable.
    """
    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    if base_point_size is not None:
        app = QApplication.instance()
        assert app is not None
        font = app.font()
        font.setPointSizeF(base_point_size)
        app.setFont(font)

    dialog = build(qtbot, roots=("/srv/one",))
    with qtbot.waitExposed(dialog):
        dialog.show()

    targets = {
        "Add": dialog._add,
        "Remove": dialog._remove,
        "poll interval": dialog._poll,
        "log cap": dialog._log,
        "single-key shortcuts": dialog._shortcuts,
        "error markers": dialog._markers,
        "Ok": dialog._buttons.button(QDialogButtonBox.StandardButton.Ok),
        "Cancel": dialog._buttons.button(QDialogButtonBox.StandardButton.Cancel),
    }

    too_small = {
        name: (widget.width(), widget.height())
        for name, widget in targets.items()
        if widget.width() < MIN_TARGET_PX or widget.height() < MIN_TARGET_PX
    }

    assert not too_small, f"below {MIN_TARGET_PX}x{MIN_TARGET_PX}: {too_small}"


def test_what_goes_in_comes_back_out_untouched(qtbot) -> None:
    """The dialog is a form, and a form that edits nothing changes nothing.

    Dies on any normalisation in `values()` — resolving the paths, sorting
    them, or de-duplicating a list the user already had.
    """
    roots = ("/srv/one", "/home/me/projects", "/srv/one/nested")

    dialog = build(qtbot, roots=roots, poll=2500, log=64)

    assert dialog.values() == (tuple(Path(r) for r in roots), 2500, 64)


@pytest.mark.parametrize("shortcuts", [True, False], ids=str)
def test_the_shortcuts_switch_comes_back_as_it_went_in_and_as_toggled(
    qtbot, shortcuts: bool
) -> None:
    """LWSM-1475. Both starting values, so a box hardwired either way fails
    one; then a Space press, the keyboard's way to flip it."""
    from PySide6.QtCore import Qt

    dialog = build(qtbot, shortcuts=shortcuts)
    assert dialog.single_key_shortcuts() is shortcuts

    qtbot.keyClick(dialog._shortcuts, Qt.Key.Key_Space)

    assert dialog.single_key_shortcuts() is (not shortcuts)
    assert "&" in dialog._shortcuts.text(), "the keyboard needs a mnemonic"


def test_the_error_markers_come_back_one_per_line_trimmed(qtbot) -> None:
    """LWSM-1036. In as the stored tuple, out as what the user left typed,
    without the blank lines and stray spaces an editor makes easy."""
    dialog = build(qtbot, markers=("ERROR", "panic:"))
    assert dialog._markers.toPlainText() == "ERROR\npanic:"
    assert dialog.error_markers() == ("ERROR", "panic:")

    dialog._markers.setPlainText("ERROR\n\n  npm ERR!  \nERROR\n")

    assert dialog.error_markers() == ("ERROR", "npm ERR!")


def test_tab_leaves_the_error_markers_box_instead_of_typing_a_tab(qtbot) -> None:
    """A text box that eats Tab is a keyboard trap (`§ O8` clause 2)."""
    from PySide6.QtCore import Qt

    dialog = build(qtbot)
    with qtbot.waitExposed(dialog):
        dialog.show()
    with qtbot.waitActive(dialog):
        dialog.activateWindow()
    dialog._markers.setFocus()

    qtbot.keyClick(dialog._markers, Qt.Key.Key_Tab)

    assert "\t" not in dialog._markers.toPlainText()
    assert not dialog._markers.hasFocus()
    assert "&" in dialog._markers_label.text(), "the keyboard needs a mnemonic"
    assert dialog._markers_label.buddy() is dialog._markers


def test_markers_the_settings_file_would_refuse_keep_the_dialog_open(qtbot) -> None:
    """Saving a list `settings.load` refuses would lose it at the next start,
    so Ok says what is wrong and stays, rather than accepting it."""
    from lwsm.settings import MAX_ERROR_MARKER_CHARS

    dialog = build(qtbot)
    with qtbot.waitExposed(dialog):
        dialog.show()
    dialog._markers.setPlainText("x" * (MAX_ERROR_MARKER_CHARS + 1))

    dialog.accept()

    assert dialog.result() != SettingsDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert str(MAX_ERROR_MARKER_CHARS) in dialog._markers_problem.text()
    assert dialog._markers_problem.isVisible()

    dialog._markers.setPlainText("ERROR")
    dialog.accept()
    assert dialog.result() == SettingsDialog.DialogCode.Accepted


def test_the_order_of_the_roots_is_the_order_they_are_scanned_in(qtbot) -> None:
    """`default_scan_roots` keeps file order because it is the walk order.

    So the dialog must not sort. Dies on a `sorted()` anywhere in `values()`
    or in the constructor's fill loop.
    """
    dialog = build(qtbot, roots=("/z-last", "/a-first"))

    assert dialog.values()[0] == (Path("/z-last"), Path("/a-first"))


def test_choosing_a_folder_adds_it(qtbot) -> None:
    dialog = build(qtbot, roots=("/srv/one",), chooser=lambda: "/srv/two")

    dialog._add_root()

    assert dialog.values()[0] == (Path("/srv/one"), Path("/srv/two"))


def test_cancelling_the_folder_chooser_adds_nothing(qtbot) -> None:
    """A cancelled chooser returns None, and that is not an error.

    Dies on dropping the `if not chosen: return` guard, which would add an
    empty string and, through `Path("")`, a root reading as the current
    directory.
    """
    dialog = build(qtbot, roots=("/srv/one",), chooser=lambda: None)

    dialog._add_root()

    assert dialog.values()[0] == (Path("/srv/one"),)


def test_choosing_a_folder_already_in_the_list_does_not_duplicate_it(qtbot) -> None:
    """Two identical roots would make the scanner walk the same tree twice."""
    dialog = build(qtbot, roots=("/srv/one",), chooser=lambda: "/srv/one")

    dialog._add_root()

    assert dialog.values()[0] == (Path("/srv/one"),)


def test_removing_two_selected_rows_removes_those_two(qtbot) -> None:
    """The one that needs more than one row selected, deliberately.

    Removing a row renumbers every row below it, so a top-down loop deletes the
    wrong entries the moment two are selected — and with a single selection it
    is indistinguishable from the correct version. This is CLAUDE.md's
    one-row-fixture trap: a fixture that cannot express the hazard cannot catch
    it.

    Dies on dropping `reverse=True` from `_remove_roots`.
    """
    dialog = build(qtbot, roots=("/a", "/b", "/c", "/d"))
    for row in (0, 2):
        dialog._roots.item(row).setSelected(True)

    dialog._remove_roots()

    assert dialog.values()[0] == (Path("/b"), Path("/d"))


def test_removing_nothing_selected_removes_nothing(qtbot) -> None:
    dialog = build(qtbot, roots=("/a", "/b"))

    dialog._remove_roots()

    assert dialog.values()[0] == (Path("/a"), Path("/b"))


def test_an_empty_list_is_a_legitimate_answer(qtbot) -> None:
    """No roots means "scan the default", which `default_scan_roots` handles.

    So there is no validation forbidding it, and this test says that is on
    purpose rather than an omission.
    """
    dialog = build(qtbot, roots=("/a",))
    dialog._roots.item(0).setSelected(True)

    dialog._remove_roots()

    assert dialog.values()[0] == ()


@pytest.mark.parametrize(
    ("attribute", "low", "high"),
    [
        ("_poll", MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS),
        ("_log", MIN_LOG_MAX_MIB, MAX_LOG_MAX_MIB),
    ],
)
def test_a_spinbox_cannot_offer_a_value_the_loader_would_refuse(
    qtbot, attribute: str, low: int, high: int
) -> None:
    """The dialog's range is `settings.py`'s range, and one fixture per box.

    A value the file's loader would refuse must not be reachable through the
    UI, or the user sets something, sees it accepted, and finds it gone on the
    next launch. Both boxes are covered because the code branches on a closed
    set of two and one wired to the wrong constant would otherwise pass.

    Dies on any change to either `setRange` call.
    """
    # The dialog is held in a name, not inlined into the `getattr`: dropping
    # the last Python reference lets PySide delete the C++ object, and the
    # spinbox then raises RuntimeError rather than failing an assertion.
    dialog = build(qtbot)
    box = getattr(dialog, attribute)

    box.setValue(low - 1)
    assert box.value() == low
    box.setValue(high + 1)
    assert box.value() == high


def test_every_control_can_be_reached_from_the_keyboard(qtbot) -> None:
    """`§ O8` clause 2 — the form is operable with no mouse.

    Asserted through `keyboard_focus_order`, which names the contract, rather
    than by reaching into the widget tree.
    """
    from PySide6.QtCore import Qt

    for policy in keyboard_focus_order(build(qtbot)):
        assert policy != Qt.FocusPolicy.NoFocus


def test_every_label_carries_a_mnemonic(qtbot) -> None:
    """A buddy label with no `&` is a label the keyboard cannot jump to."""
    dialog = build(qtbot)

    for label in (dialog._roots_label, dialog._poll_label, dialog._log_label):
        assert "&" in label.text(), f"{label.text()!r} has no mnemonic"
        assert label.buddy() is not None, f"{label.text()!r} has no buddy"


def test_a_language_change_retranslates_the_form(qtbot) -> None:
    """One method answers LanguageChange, the rule `_retranslate_menus` sets.

    Sent by hand: `installTranslator` only broadcasts once the event loop is
    running, and even then Qt was measured not to deliver it to a window in
    this shape (CLAUDE.md). So this proves the handler is wired and does NOT
    prove a real translator reaches it.
    """
    from PySide6.QtCore import QEvent

    dialog = build(qtbot)
    dialog._roots_label.setText("stale")

    dialog.changeEvent(QEvent(QEvent.Type.LanguageChange))

    assert dialog._roots_label.text() != "stale"


def _roots_reporting_focus(dialog: SettingsDialog) -> list[str]:
    """The folders whose accessible state says FOCUSED."""
    from PySide6.QtGui import QAccessible

    roots = QAccessible.queryAccessibleInterface(dialog._roots)
    focused = []
    for i in range(roots.childCount()):
        item = roots.child(i)
        if item.state().focused:
            focused.append(item.text(QAccessible.Text.Name))
    return focused


def test_a_folder_reports_focused_only_while_the_list_has_focus(qtbot) -> None:
    """LWSM-1505. Qt marks a list's CURRENT item focused whether or not the
    list has focus, so with the poll box focused the bus still said "/srv/a"
    had the focus (measured on a private AT-SPI bus, 2026-11-05) — the same
    cause as LWSM-1504's browser picker. Coming back must land on the folder
    the user left, not the first one, with the selection untouched; and when
    the folders removed include the last one, on the new last folder."""
    from PySide6.QtCore import Qt

    dialog = build(qtbot, roots=("/srv/a", "/srv/b", "/srv/c", "/srv/d"))
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: dialog.isActiveWindow())
    roots = dialog._roots

    roots.setFocus(Qt.FocusReason.TabFocusReason)
    roots.setCurrentRow(3)
    roots.item(2).setSelected(True)
    assert roots.hasFocus()
    assert _roots_reporting_focus(dialog) == ["/srv/d"]

    dialog._poll.setFocus(Qt.FocusReason.TabFocusReason)
    assert not roots.hasFocus()
    assert _roots_reporting_focus(dialog) == []

    roots.setFocus(Qt.FocusReason.BacktabFocusReason)
    assert roots.currentRow() == 3, "coming back lost the folder the user left"
    assert _roots_reporting_focus(dialog) == ["/srv/d"]
    # Remove acts on the selection, so coming back must not change it.
    assert sorted(item.text() for item in roots.selectedItems()) == [
        "/srv/c",
        "/srv/d",
    ]

    # Read from the view, not the accessible children: with no screen reader
    # attached, Qt's cached cells still name the removed rows (measured).
    # Qt's own fallback is the FIRST folder, which is what this tells apart.
    dialog._remove.setFocus(Qt.FocusReason.TabFocusReason)
    dialog._remove_roots()
    roots.setFocus(Qt.FocusReason.BacktabFocusReason)
    assert roots.currentItem() is not None, "nowhere for the keyboard to start"
    assert roots.currentItem().text() == "/srv/b", "not the new last folder"
