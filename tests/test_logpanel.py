"""LWSM-1015 — the live log panel, in the window.

The core half (the ring, the followers, the journal argv) is
`test_logbuffer.py`'s; where a project's output comes from is
`test_controller.py`'s. These tests are the widget: plain text only, follow
unless the user has scrolled up, say so when a server's output is not ours to
show, and open from the row by keyboard.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit

from lwsm import controller as controller_module
from lwsm.controller import ProjectController, ProjectStatus, RowView
from lwsm.logbuffer import LogSource
from lwsm.mainwindow import MIN_TARGET_PX, MainWindow, ProjectRow
from lwsm.ports import PortSnapshot
from lwsm.registry import ProjectRecord
from lwsm.theme import Theme

pytestmark = pytest.mark.gui

OUR_PID = 4242
STRANGER_PID = 9999


@pytest.fixture(autouse=True)
def _holders_look_like_their_projects(monkeypatch) -> None:
    """A stranger's process that looks like the project, in no unit of its
    own: ADR-0004's `running (foreign)`."""
    monkeypatch.setattr(controller_module, "looks_like", lambda pid, project: True)
    monkeypatch.setattr(controller_module, "unit_for_pid", lambda pid: None)
    monkeypatch.setattr(
        controller_module, "unit_belongs_to", lambda unit, project: False
    )


class Probe:
    def __init__(self, holders: dict[int, int]) -> None:
        self.holders = holders

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(frozenset(self.holders), dict(self.holders))


class LogDirSupervisor:
    """Holds a child for `ours`, and keeps every log in `log_dir`."""

    def __init__(self, log_dir: Path, ours=()) -> None:
        self.log_dir = log_dir
        self._running = {Path(path): object() for path in ours}

    def running(self) -> dict:
        return dict(self._running)

    def owns_pid(self, project: Path, pid: int) -> bool:
        return Path(project) in self._running and pid == OUR_PID

    def exited(self, project: Path) -> bool:
        return False

    def is_stopping(self, project: Path) -> bool:
        return False

    def log_path_for(self, project: Path, name: str) -> Path:
        return self.log_dir / f"{name}.log"


def record(name: str, port: int) -> ProjectRecord:
    return ProjectRecord(
        path=Path(f"/srv/{name}"), name=name, port=port, port_override=None
    )


@pytest.fixture
def windows() -> Iterator[list[tuple[MainWindow, ProjectController]]]:
    built: list[tuple[MainWindow, ProjectController]] = []
    yield built
    for window, controller in built:
        window.shutdown()
        controller.stop()


def log_window(qtbot, windows, tmp_path, holders, ours=("/srv/web",), extra=()):
    supervisor = LogDirSupervisor(tmp_path, ours)
    records = [record("web", 5005), *extra]
    controller = ProjectController(records, Probe(holders), supervisor)
    window = MainWindow(controller, Theme.default(), [])
    windows.append((window, controller))
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    with qtbot.waitExposed(window):
        window.show()
    return window, controller, tmp_path / "web.log"


def row_of(window: MainWindow) -> ProjectRow:
    return window._rows[Path("/srv/web")]


def test_the_output_is_shown_as_plain_text_and_never_rendered(
    qtbot, windows, tmp_path
) -> None:
    """LWSM-1049, inherited: Qt's auto-detected rich text loads local
    resources, so a server printing markup must be shown it, not drawn."""
    window, _, log = log_window(qtbot, windows, tmp_path, {5005: OUR_PID})
    hostile = "<b>bold</b> <img src='file:///etc/hostname'> &amp;"
    log.write_text(hostile + "\n")

    window.show_output(Path("/srv/web"))
    panel = window._log_panel
    qtbot.waitUntil(lambda: hostile in panel.view.toPlainText(), timeout=3000)

    assert type(panel.view) is QPlainTextEdit
    assert panel.view.isReadOnly()
    assert panel.view.document().toPlainText() == hostile


def test_the_view_follows_new_output_unless_the_user_has_scrolled_up(
    qtbot, windows, tmp_path
) -> None:
    """Both halves in one test, so neither can hold on its own: a view that
    never scrolled would pass the second, one that always did the first."""
    window, _, _ = log_window(qtbot, windows, tmp_path, {5005: OUR_PID})
    window.show_output(Path("/srv/web"))
    panel = window._log_panel
    bar = panel.view.verticalScrollBar()

    panel.append_lines([f"line {n}" for n in range(300)])
    assert bar.maximum() > 0, "the fixture must overflow the view"
    assert bar.value() == bar.maximum(), "new output was not followed"
    assert "Following" in panel.status.text()

    bar.setValue(0)
    panel.append_lines([f"more {n}" for n in range(50)])
    assert bar.value() == 0, "the view jumped away from what the user was reading"
    assert "Paused" in panel.status.text()

    bar.setValue(bar.maximum())
    panel.append_lines(["back"])
    assert bar.value() == bar.maximum()
    assert "Following" in panel.status.text()


def test_a_foreign_server_says_its_output_is_not_available(
    qtbot, windows, tmp_path
) -> None:
    """design.md § Observability: a server this app did not start writes
    nothing it can read, so the panel says so rather than showing an empty
    view as though the server were silent."""
    window, controller, _ = log_window(
        qtbot, windows, tmp_path, {5005: STRANGER_PID}, ours=()
    )
    assert controller.row(Path("/srv/web")).status is ProjectStatus.RUNNING_FOREIGN

    window.show_output(Path("/srv/web"))
    panel = window._log_panel

    assert "not started by this app" in panel.status.text()
    assert panel.view.toPlainText() == ""


def test_the_tail_is_still_shown_after_the_server_has_exited(
    qtbot, windows, tmp_path
) -> None:
    """Criterion 5: a server that died on startup is diagnosable without a
    terminal. Nothing holds the port; the file still has its last words."""
    window, _, log = log_window(qtbot, windows, tmp_path, {}, ours=())
    log.write_text("Traceback (most recent call last):\nOSError: address in use")

    window.show_output(Path("/srv/web"))
    view = window._log_panel.view

    qtbot.waitUntil(
        lambda: view.toPlainText().endswith("OSError: address in use"), timeout=3000
    )


def test_the_panel_opens_from_the_row_and_takes_the_focus(
    qtbot, windows, tmp_path
) -> None:
    """Keyboard first: the row's own action, from its context menu or
    Ctrl+L. Focus moves into the output so a magnifier and a screen reader
    both land on it; that is the user's own request, not stolen focus."""
    window, _, _ = log_window(qtbot, windows, tmp_path, {5005: OUR_PID})
    with qtbot.waitActive(window):
        window.activateWindow()
    row = row_of(window)
    row.setFocus()

    assert row.show_output_action in row.actions(), "not in the row's menu"
    qtbot.keyClick(row, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)

    panel = window._log_panel
    assert panel.isVisible()
    assert "web" in panel.title.text()
    assert panel.view.hasFocus()
    assert panel.view.accessibleName() == "Output of web"


def test_escape_closes_the_panel_and_returns_to_the_row(
    qtbot, windows, tmp_path
) -> None:
    """Back to the row the output belongs to — the SECOND of two here. When
    a focused widget hides, Qt moves focus to the next in the chain, and
    rows join the chain after the panel, so for the first row Qt's own
    choice would pass for this one (a mutant survived on that fixture)."""
    window, _, _ = log_window(
        qtbot, windows, tmp_path, {5005: OUR_PID}, extra=[record("api", 6006)]
    )
    with qtbot.waitActive(window):
        window.activateWindow()
    window.show_output(Path("/srv/api"))
    panel = window._log_panel
    assert panel.view.hasFocus()

    qtbot.keyClick(panel.view, Qt.Key.Key_Escape)

    assert not panel.isVisible()
    assert window._rows[Path("/srv/api")].hasFocus()
    assert panel.feed is None, "the follower outlived the panel"


def test_tab_reaches_the_panel_after_the_list_it_sits_under(
    qtbot, windows, tmp_path
) -> None:
    """Tab order follows visual order (design-accessibility.md). Rows join
    Qt's focus chain when they are parented, after the panel was built, so
    left alone Tab reached the panel before the list above it."""
    window, _, _ = log_window(
        qtbot, windows, tmp_path, {5005: OUR_PID}, extra=[record("api", 6006)]
    )
    window.show_output(Path("/srv/web"))
    panel = window._log_panel
    last_row = window._rows[Path("/srv/api")]

    chain = []
    widget = window._filter.nextInFocusChain()
    while widget is not window._filter:
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus and widget.isVisible():
            chain.append(widget)
        widget = widget.nextInFocusChain()

    assert chain.index(panel.close_button) > chain.index(last_row.open_button)
    # LWSM-1036 put the error controls between Close and the output, as they
    # sit on screen; their own test pins the order.
    assert chain.index(panel.jump_button) == chain.index(panel.close_button) + 1


def test_the_panel_controls_are_named_and_big_enough_to_hit(
    qtbot, windows, tmp_path
) -> None:
    window, _, _ = log_window(qtbot, windows, tmp_path, {5005: OUR_PID})
    window.show_output(Path("/srv/web"))
    panel = window._log_panel

    assert panel.close_button.accessibleName() == "Close the output of web"
    assert panel.close_button.height() >= MIN_TARGET_PX
    assert panel.view.accessibleDescription() == panel.status.text()
    # Readable, not a sliver: a few lines at the least, whatever the list.
    lines = panel.view.fontMetrics().lineSpacing()
    assert panel.view.height() >= 6 * lines


def failed_view(status: ProjectStatus) -> RowView:
    return RowView(
        path=Path("/srv/web"), name="web", effective_port=5005, status=status
    )


def test_a_failed_row_offers_its_output_next_to_it(qtbot) -> None:
    """Feedback where the action happened: the row that failed carries the
    way to read why, visible at rest rather than only in a menu."""
    row = ProjectRow(failed_view(ProjectStatus.FAILED), Theme.default())
    qtbot.addWidget(row)
    triggered: list[bool] = []
    row.show_output_action.triggered.connect(lambda *_: triggered.append(True))

    button = row.output_button
    assert button is not None
    assert button.text() == "View output"
    assert button.accessibleName() == "View the output of web"
    assert button.height() >= MIN_TARGET_PX or button.minimumHeight() >= MIN_TARGET_PX
    button.click()
    assert triggered == [True]

    row.update_from(failed_view(ProjectStatus.STOPPED))
    assert row.output_button is None, "the offer outlived the failure"


def test_a_source_with_no_file_and_no_unit_says_there_is_nothing(qtbot) -> None:
    """A window built with no supervisor has no log directory."""
    from lwsm.logpanel import LogPanel

    panel = LogPanel()
    qtbot.addWidget(panel)
    panel.open_for("web", LogSource())
    assert "no output" in panel.status.text().lower()
    panel.close_panel()


# --- LWSM-1036: find the error in the log -------------------------------------

NOISE = [f"GET /page/{n} 200" for n in range(200)]


@pytest.fixture
def heard(monkeypatch) -> list[str]:
    """What the panel announced to a screen reader, in order."""
    from lwsm import logpanel

    said: list[str] = []
    monkeypatch.setattr(logpanel, "_announce", lambda widget, text: said.append(text))
    return said


def open_panel(qtbot, windows, tmp_path):
    window, _, _ = log_window(qtbot, windows, tmp_path, {5005: OUR_PID})
    with qtbot.waitActive(window):
        window.activateWindow()
    window.show_output(Path("/srv/web"))
    return window, window._log_panel


def test_jump_to_last_error_selects_it_shows_it_and_says_it(
    qtbot, windows, tmp_path, heard
) -> None:
    """The point of the item: the app finds the line, so a magnifier user
    does not scroll for it. The LAST error, with an earlier one present, so a
    jump to the first would fail; and noise after it, so the bottom is not it."""
    _, panel = open_panel(qtbot, windows, tmp_path)
    panel.append_lines(
        ["ERROR first failure", *NOISE, "Traceback (most recent call last):", *NOISE]
    )
    bar = panel.view.verticalScrollBar()
    assert bar.value() == bar.maximum()

    panel.jump_button.setFocus()
    qtbot.keyClick(panel.jump_button, Qt.Key.Key_Space)

    cursor = panel.view.textCursor()
    assert cursor.block().text() == "Traceback (most recent call last):"
    assert cursor.selectedText() == "Traceback (most recent call last):"
    assert bar.value() < bar.maximum(), "the line was not scrolled into view"
    # Centred, so the lines after it (the rest of a traceback) are in view
    # too, not one line at the very edge of the lens.
    middle = panel.view.viewport().height() / 2
    assert abs(panel.view.cursorRect().center().y() - middle) < middle / 2
    assert panel.view.hasFocus(), "the lens follows focus; it was left behind"
    assert heard[-1] == "Last error: Traceback (most recent call last):"
    assert "Last error" in panel.status.text()
    assert panel.view.accessibleDescription() == panel.status.text()

    # Reading it must not be interrupted by more output.
    panel.append_lines(["more"])
    assert panel.view.textCursor().block().text().startswith("Traceback")
    assert bar.value() < bar.maximum()


def test_jump_with_no_error_says_so_and_moves_nothing(
    qtbot, windows, tmp_path, heard
) -> None:
    _, panel = open_panel(qtbot, windows, tmp_path)
    panel.append_lines(NOISE)
    bar = panel.view.verticalScrollBar()

    panel.jump_button.click()

    assert bar.value() == bar.maximum()
    assert heard[-1] == "No error lines in this output."
    assert "No error lines" in panel.status.text()


def test_errors_only_shows_error_lines_and_off_brings_the_rest_back(
    qtbot, windows, tmp_path
) -> None:
    """Both directions, and output arriving while filtered: a filter applied
    only to what was already shown would let new noise straight through."""
    _, panel = open_panel(qtbot, windows, tmp_path)
    feed = panel.feed
    assert feed is not None
    every = ["boot", "ERROR one", "ok", "exited with code 2"]
    feed.buffer.feed("\n".join(every) + "\n")
    panel.append_lines(every)

    qtbot.keyClick(panel.errors_only, Qt.Key.Key_Space)
    assert panel.errors_only.isChecked()
    assert panel.view.toPlainText().splitlines() == ["ERROR one", "exited with code 2"]
    assert "only" in panel.status.text().lower()

    feed.buffer.feed("noise\nCRITICAL two\n")
    panel.append_lines(["noise", "CRITICAL two"])
    assert panel.view.toPlainText().splitlines()[-1] == "CRITICAL two"
    assert "noise" not in panel.view.toPlainText()

    panel.errors_only.click()
    assert panel.view.toPlainText().splitlines() == [*every, "noise", "CRITICAL two"]


def test_the_window_hands_the_panel_the_markers_in_force(
    qtbot, windows, tmp_path, heard
) -> None:
    """Preferences changes the set while the panel is open; the next jump
    uses the new set, and a filtered view is redrawn by it."""
    window, panel = open_panel(qtbot, windows, tmp_path)
    panel.append_lines(["panic: nil map", *NOISE])

    panel.jump_button.click()
    assert heard[-1] == "No error lines in this output."

    window.set_error_markers(("panic:",))
    assert window.error_markers() == ("panic:",)
    panel.jump_button.click()
    assert heard[-1] == "Last error: panic: nil map"


def test_the_error_controls_are_named_reachable_and_big_enough(
    qtbot, windows, tmp_path
) -> None:
    """`§ O8`: a name, a mnemonic for the keyboard, the target floor, and a
    place in the tab order between Close and the output."""
    window, panel = open_panel(qtbot, windows, tmp_path)

    assert panel.jump_button.text() == "Jump to last &error"
    assert panel.errors_only.text() == "Errors &only"
    assert (
        panel.jump_button.accessibleName()
        == "Jump to the last error in the output of web"
    )
    for control in (panel.jump_button, panel.errors_only):
        assert control.height() >= MIN_TARGET_PX
        assert control.focusPolicy() & Qt.FocusPolicy.TabFocus

    chain = []
    widget = window._filter.nextInFocusChain()
    while widget is not window._filter:
        if widget.focusPolicy() & Qt.FocusPolicy.TabFocus and widget.isVisible():
            chain.append(widget)
        widget = widget.nextInFocusChain()
    at = chain.index(panel.close_button)
    assert chain[at : at + 4] == [
        panel.close_button,
        panel.jump_button,
        panel.errors_only,
        panel.view,
    ]


def test_opening_another_project_clears_the_last_jump(
    qtbot, windows, tmp_path, heard
) -> None:
    """A notice about web's error must not sit over api's output."""
    window, _, _ = log_window(
        qtbot, windows, tmp_path, {5005: OUR_PID}, extra=[record("api", 6006)]
    )
    window.show_output(Path("/srv/web"))
    panel = window._log_panel
    panel.append_lines(["ERROR web broke"])
    panel.jump_button.click()
    assert "Last error" in panel.status.text()

    window.show_output(Path("/srv/api"))
    assert "Last error" not in panel.status.text()
