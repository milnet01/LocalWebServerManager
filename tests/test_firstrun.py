"""LWSM-1008 — the first-run confirmation dialog.

The dialog owns no I/O: it is handed records and returns records, and the write
is `MainWindow._apply_merge`'s, tested in `test_mainwindow.py`. So every test
here is about what the widgets do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from lwsm import firstrun
from lwsm.firstrun import FirstRunDialog, describe
from lwsm.mainwindow import MIN_TARGET_PX
from lwsm.registry import ProjectRecord

pytestmark = pytest.mark.gui


def project(name: str, port: int | None = 3000) -> ProjectRecord:
    return ProjectRecord(
        path=Path("/srv") / name, name=name, port=port, argv=("./run.sh",)
    )


def build(qtbot, records, skipped=()) -> FirstRunDialog:
    dialog = FirstRunDialog(records, skipped)
    qtbot.addWidget(dialog)
    return dialog


def test_every_project_starts_ticked(qtbot) -> None:
    records = [project("api"), project("web")]
    dialog = build(qtbot, records)

    assert dialog.chosen() == records
    assert dialog._count.text() == "Ticked: 2 of 2"


def test_an_unticked_project_is_left_out(qtbot) -> None:
    dialog = build(qtbot, [project("api"), project("web")])

    dialog._boxes[0].setChecked(False)

    assert [record.name for record in dialog.chosen()] == ["web"]
    assert dialog._count.text() == "Ticked: 1 of 2"


def test_each_line_names_the_project_what_starts_it_and_its_port(qtbot) -> None:
    assert describe(project("web")) == "web — ./run.sh, port 3000"
    assert describe(project("web", port=None)) == "web — ./run.sh, port not found"


def test_an_ampersand_in_a_name_is_shown_not_taken_as_a_shortcut(qtbot) -> None:
    dialog = build(qtbot, [project("R&D")])

    assert dialog._boxes[0].text().startswith("R&&D")


def test_the_scan_reasons_are_shown_and_hidden_when_there_are_none(qtbot) -> None:
    shown = build(qtbot, [project("web")], ("'notes': no launcher matched",))
    none = build(qtbot, [project("web")])

    assert "'notes': no launcher matched" in shown._skipped.text()
    assert not shown._skipped.isHidden()
    assert none._skipped.isHidden()
    assert none._skipped_title.isHidden()


def test_an_empty_scan_still_offers_save(qtbot) -> None:
    """LWSM-1131 § 4.4: a first run finding nothing must still be able to
    create the file, or every later start repeats the first run."""
    dialog = build(qtbot, [])

    assert "No projects were found" in dialog._intro.text()
    assert dialog._save.isEnabled()
    assert dialog.chosen() == []


def test_the_buttons_and_boxes_clear_the_target_size_floor(qtbot) -> None:
    dialog = build(qtbot, [project("web")])

    for widget in (dialog._save, dialog._later, dialog._boxes[0]):
        assert widget.minimumHeight() >= MIN_TARGET_PX


@pytest.mark.parametrize(
    ("code", "expected"),
    [(QDialog.DialogCode.Accepted, ["web"]), (QDialog.DialogCode.Rejected, None)],
)
def test_ask_returns_the_ticked_records_or_none(
    qtbot, monkeypatch, code, expected
) -> None:
    """Save returns the ticked records; Not now returns `None`, never `[]`,
    which would save an empty list over a choice the user put off."""
    monkeypatch.setattr(FirstRunDialog, "exec", lambda self: code)

    chosen = firstrun.ask_first_run([project("web")], (), None)

    assert (None if chosen is None else [r.name for r in chosen]) == expected
