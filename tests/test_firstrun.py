"""LWSM-1008 — the first-run confirmation dialog.

The dialog owns no I/O: it is handed records and returns records, and the write
is `MainWindow._apply_merge`'s, tested in `test_mainwindow.py`. So every test
here is about what the widgets do.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from lwsm import firstrun, scanner
from lwsm.firstrun import FirstRunDialog, describe
from lwsm.mainwindow import MIN_TARGET_PX
from lwsm.registry import ProjectRecord
from scanner_fixtures import FakeUnits

pytestmark = pytest.mark.gui


def project(name: str, port: int | None = 3000) -> ProjectRecord:
    return ProjectRecord(
        path=Path("/srv") / name, name=name, port=port, argv=("./run.sh",)
    )


def build(qtbot, records, skipped=(), units_unavailable=False) -> FirstRunDialog:
    dialog = FirstRunDialog(records, skipped, units_unavailable=units_unavailable)
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


def test_a_scanned_direction_override_cannot_reverse_the_line(tmp_path) -> None:
    """LWSM-1469: a folder named `evil<U+202E>` drew "- ./start.sh, port 3000"
    reversed in the check box the user approves projects in. Through the real
    scanner, which names the project from the folder."""
    folder = tmp_path / "evil‮"
    folder.mkdir()
    (folder / "start.sh").write_text("#!/bin/sh\nPORT=3000 exec true\n")
    (folder / "start.sh").chmod(0o755)
    [found] = scanner.scan([tmp_path], units=FakeUnits()).projects

    line = describe(
        ProjectRecord(path=found.path, name=found.name, port=3000, argv=found.argv)
    )

    assert not any("‪" <= c <= "‮" or "⁦" <= c <= "⁩" for c in line)


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


def test_only_real_folders_are_listed_as_not_added(qtbot) -> None:
    """LWSM-1383 (user, 2026-10-02): plain files and dot-folders are left out
    of the dialog; the tail line and a folder's own reason stay."""
    dialog = build(
        qtbot,
        [project("web")],
        (
            "'notes': no launcher matched",
            "'README.md': is not a directory",
            "'.cache': no launcher matched",
            '".it\'s": cannot be examined (Permission denied)',
            "and 3 more problems, not shown",
        ),
    )

    assert dialog._skipped.text().splitlines() == [
        "'notes': no launcher matched",
        "and 3 more problems, not shown",
    ]


def test_a_scan_of_only_files_and_dot_folders_shows_no_list(qtbot) -> None:
    """Nothing left after the filter hides the heading too, not just the text."""
    dialog = build(qtbot, [project("web")], ("'a.txt': is not a directory",))

    assert dialog._skipped.isHidden()
    assert dialog._skipped_title.isHidden()


def test_the_filter_matches_the_real_scanners_wording(qtbot, tmp_path) -> None:
    """`worth_showing` reads the scanner's reason strings, so this runs the
    real scanner: a reworded reason fails here instead of quietly coming back."""
    (tmp_path / "notes").mkdir()
    (tmp_path / ".cache").mkdir()
    (tmp_path / "README.md").write_text("")
    result = scanner.scan([tmp_path], units=FakeUnits())
    assert len(result.skipped) == 3  # the scanner still reports all three

    dialog = build(qtbot, [], result.skipped)

    assert dialog._skipped.text() == "'notes': no launcher matched"


def test_the_hidden_entries_tail_is_hidden_too(qtbot, tmp_path) -> None:
    """LWSM-1384: the scanner's second budget holds only lines the dialog
    hides, so its "and N more" line would be the one noise line left. Runs
    the real scanner for the reason the test above gives."""
    for index in range(scanner.MAX_SKIP_REASONS + 5):
        (tmp_path / f"f-{index:04d}.txt").write_text("")
    (tmp_path / "notes").mkdir()
    result = scanner.scan([tmp_path], units=FakeUnits())

    dialog = build(qtbot, [], result.skipped)

    assert dialog._skipped.text() == "'notes': no launcher matched"


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


# --- review-code 2026-10-08, lane 9 --------------------------------------------


def test_the_counts_use_the_locales_digits(qtbot) -> None:
    """L09-L1. `str(len(...))` writes Western digits whatever the locale; the
    window formats its numbers with `QLocale().toString`, and so must this.

    Dies on `str()` for either count.
    """
    from PySide6.QtCore import QLocale

    previous = QLocale()
    QLocale.setDefault(QLocale(QLocale.Language.Arabic, QLocale.Country.Egypt))
    try:
        dialog = build(qtbot, [project("a"), project("b")])
    finally:
        QLocale.setDefault(previous)

    text = dialog._count.text()
    assert "٢" in text, f"no Arabic-Indic two in {text!r}"
    assert "2" not in text, f"a Western digit in {text!r}"


def test_each_projects_line_is_retranslated_with_the_rest(qtbot, monkeypatch) -> None:
    """L09-L2. `_retranslate` promises every user-visible string, and each
    check box's line was set once at construction and never again on a
    language change.

    Dies on setting the line only in `__init__`.
    """
    from PySide6.QtCore import QEvent

    dialog = build(qtbot, [project("a")])
    monkeypatch.setattr(firstrun, "describe", lambda record: "in another language")

    dialog.changeEvent(QEvent(QEvent.Type.LanguageChange))

    assert dialog._boxes[0].text() == "in another language"


def test_the_skipped_list_is_not_a_tab_stop(qtbot) -> None:
    """L09-M1 claimed that keyboard selection makes this label a Tab stop with
    no ring. Measured on PySide6 6.12.0 (2026-10-08): it gets ClickFocus, as
    mouse selection alone does; only keyboard-accessible LINKS make a label a
    Tab stop. This pins that, so a change that makes it one is seen.
    """
    from PySide6.QtCore import Qt

    dialog = build(qtbot, [project("a")], ["skipped: b (no launcher)"])

    assert not dialog._skipped.focusPolicy() & Qt.FocusPolicy.TabFocus


# --- a first run where systemd could not be asked (user, 2026-11-14) ----------

NOTE = "Services could not be checked"


def test_when_services_could_not_be_checked_nothing_starts_ticked(qtbot) -> None:
    """A wrong guess about a unit would be saved; the user ticks by hand."""
    records = [project("api"), project("web")]
    dialog = build(qtbot, records, units_unavailable=True)

    assert dialog.chosen() == []
    assert dialog._count.text() == "Ticked: 0 of 2"
    assert all(not box.isChecked() for box in dialog._boxes)

    dialog._boxes[1].setChecked(True)

    assert [record.name for record in dialog.chosen()] == ["web"]
    assert dialog._count.text() == "Ticked: 1 of 2"


def test_every_row_carries_the_note_and_the_intro_says_to_tick(qtbot) -> None:
    dialog = build(qtbot, [project("api"), project("web")], units_unavailable=True)

    for box, name in zip(dialog._boxes, ("api", "web"), strict=True):
        assert box.text() == f"{name} — ./run.sh, port 3000\n{NOTE}"
    assert dialog._intro.text().startswith(NOTE)
    assert "Tick" in dialog._intro.text()
    assert "Untick" not in dialog._intro.text()


def test_a_normal_first_run_has_no_note_and_starts_ticked(qtbot) -> None:
    dialog = build(qtbot, [project("api")])

    assert dialog._boxes[0].isChecked()
    assert NOTE not in dialog._boxes[0].text()
    assert NOTE not in dialog._intro.text()


def test_the_note_is_retranslated_with_the_rest(qtbot) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent, QTranslator
    from PySide6.QtWidgets import QApplication

    class Shouting(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            return sourceText.upper()

    dialog = build(qtbot, [project("api")], units_unavailable=True)
    translator = Shouting()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        QApplication.sendEvent(dialog, QEvent(QEvent.Type.LanguageChange))

        assert NOTE.upper() in dialog._boxes[0].text()
        assert dialog._intro.text().startswith(NOTE.upper())
    finally:
        app.removeTranslator(translator)


def test_the_note_fits_at_double_text_size(qtbot) -> None:
    """The note is a second line of the box, so the box grows taller rather
    than wider, and the intro wraps; at 200 % nothing needs a sideways scroll
    that the plain line did not."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    original = app.font()
    try:
        font = app.font()
        font.setPointSizeF(font.pointSizeF() * 2)
        app.setFont(font)
        plain = build(qtbot, [project("web")])
        noted = build(qtbot, [project("web")], units_unavailable=True)

        box = noted._boxes[0]
        line = box.fontMetrics().lineSpacing()
        assert box.sizeHint().height() >= 2 * line
        # Two lines, not one long one: a single line would be the sum of both.
        one_line = plain._boxes[
            0
        ].sizeHint().width() + box.fontMetrics().horizontalAdvance(NOTE)
        assert box.sizeHint().width() < one_line
        assert noted._intro.wordWrap()
    finally:
        app.setFont(original)


def test_ask_passes_the_flag_to_the_dialog(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        FirstRunDialog, "exec", lambda self: QDialog.DialogCode.Accepted
    )

    chosen = firstrun.ask_first_run([project("web")], (), None, units_unavailable=True)

    assert chosen == []
