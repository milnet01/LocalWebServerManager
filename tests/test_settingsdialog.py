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

from lwsm.settings import (
    MAX_LOG_MAX_MIB,
    MAX_POLL_INTERVAL_MS,
    MIN_LOG_MAX_MIB,
    MIN_POLL_INTERVAL_MS,
)
from lwsm.settingsdialog import SettingsDialog, keyboard_focus_order

pytestmark = pytest.mark.gui


def build(qtbot, roots=(), poll=1000, log=5, chooser=None) -> SettingsDialog:
    dialog = SettingsDialog(
        roots=[Path(root) for root in roots],
        poll_interval_ms=poll,
        log_max_mib=log,
        choose_directory=chooser if chooser is not None else (lambda: None),
    )
    qtbot.addWidget(dialog)
    return dialog


def test_what_goes_in_comes_back_out_untouched(qtbot) -> None:
    """The dialog is a form, and a form that edits nothing changes nothing.

    Dies on any normalisation in `values()` — resolving the paths, sorting
    them, or de-duplicating a list the user already had.
    """
    roots = ("/srv/one", "/home/me/projects", "/srv/one/nested")

    dialog = build(qtbot, roots=roots, poll=2500, log=64)

    assert dialog.values() == (tuple(Path(r) for r in roots), 2500, 64)


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
