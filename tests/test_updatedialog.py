"""LWSM-1548 — the update window. INV-13 and INV-14 of
`docs/specs/LWSM-1548-appimage-self-update.md`, and its buttons.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QTextDocument
from PySide6.QtWidgets import QAbstractButton, QPushButton

from lwsm import update_fetch, updatedialog
from lwsm.update import Release
from lwsm.updatedialog import UpdateDialog

pytestmark = pytest.mark.gui

HOSTILE_NOTES = (
    "See [the page](https://example.invalid/page).\n\n"
    "![x](file:///etc/hostname)\n\n"
    "Some <b>raw</b> text."
)


class FakeInstaller(QObject):
    progress = Signal(int, int)
    installed = Signal(object)
    failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.started = 0
        self.cancelled = 0

    def start(self) -> None:
        self.started += 1

    def cancel(self) -> None:
        self.cancelled += 1
        self.failed.emit(update_fetch.INSTALL_INCOMPLETE, update_fetch.CANCELLED)


def _release(version=(0, 7, 0), body: str = HOSTILE_NOTES) -> Release:
    url = "https://github.invalid/a.AppImage"
    return Release(version, body, url, url + ".sig", 100)


@pytest.fixture
def made() -> list[FakeInstaller]:
    return []


@pytest.fixture
def dialog(qtbot, made: list[FakeInstaller]) -> UpdateDialog:
    def make(release, path, owner) -> FakeInstaller:
        installer = FakeInstaller()
        made.append(installer)
        return installer

    offered = _release()
    window = UpdateDialog(
        (0, 5, 1),
        offered,
        [offered, _release((0, 6, 0), "Older notes.")],
        "/apps/lwsm.AppImage",
        make_installer=make,  # type: ignore[arg-type]
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


# INV-13


def test_the_notes_load_nothing_open_nothing_and_render_no_html(
    dialog: UpdateDialog, monkeypatch, qtbot
) -> None:
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url))
    notes = dialog._notes

    text = notes.document().toPlainText()
    assert "<b>raw</b>" in text
    assert "Version 0.7.0" in text and "Version 0.6.0" in text
    assert text.index("Version 0.7.0") < text.index("Version 0.6.0")
    for url in ("file:///etc/hostname", "https://example.invalid/page"):
        assert (
            notes.loadResource(QTextDocument.ResourceType.ImageResource, QUrl(url))
            is None
        )
    assert notes.openLinks() is False
    assert notes.openExternalLinks() is False

    # Activate the link the way a user would: find it and click it.
    cursor = notes.document().find("the page")
    rect = notes.cursorRect(cursor)
    qtbot.mouseClick(
        notes.viewport(), Qt.MouseButton.LeftButton, pos=rect.center() - QPoint(2, 0)
    )
    assert opened == []
    assert notes.source() == QUrl()


# INV-14


def test_the_window_is_non_modal_named_and_has_no_default(dialog: UpdateDialog) -> None:
    assert dialog.isModal() is False
    for button in dialog.findChildren(QAbstractButton):
        assert button.accessibleName(), button.text()
    assert dialog._notes.accessibleName()
    assert not [b.text() for b in dialog.findChildren(QPushButton) if b.isDefault()]


def test_enter_installs_nothing(dialog: UpdateDialog, qtbot, made) -> None:
    qtbot.keyClick(dialog, Qt.Key.Key_Return)
    assert made == []


def test_the_window_is_never_opened_with_exec() -> None:
    source = Path(updatedialog.__file__).read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "exec"
    ]
    assert calls == []


# The buttons


def test_update_now_starts_one_install_and_shows_cancel(
    dialog: UpdateDialog, qtbot, made
) -> None:
    qtbot.mouseClick(dialog._update, Qt.MouseButton.LeftButton)

    assert [i.started for i in made] == [1]
    assert dialog._cancel.isVisible()
    assert dialog._progress.isVisible()
    assert not dialog._update.isVisible()
    assert dialog._progress.maximum() == 100


@pytest.mark.parametrize(
    ("kind", "detail", "words"),
    [
        (update_fetch.INSTALL_INCOMPLETE, "unreachable", "didn't finish"),
        (update_fetch.INSTALL_UNVERIFIED, "", "couldn't be proved"),
        (update_fetch.INSTALL_UNWRITABLE, "/opt/apps", "replace itself in /opt/apps"),
        (update_fetch.INSTALL_WRITE_FAILED, "No space left", "No space left"),
    ],
)
def test_a_failure_is_said_and_the_buttons_return(
    dialog: UpdateDialog, qtbot, made, kind, detail, words
) -> None:
    qtbot.mouseClick(dialog._update, Qt.MouseButton.LeftButton)
    made[0].failed.emit(kind, detail)

    assert words in dialog._message.text()
    assert dialog._message.isVisible()
    assert dialog._update.isVisible()
    assert not dialog._cancel.isVisible()


def test_cancel_stops_the_download(dialog: UpdateDialog, qtbot, made) -> None:
    qtbot.mouseClick(dialog._update, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog._cancel, Qt.MouseButton.LeftButton)

    assert made[0].cancelled == 1
    assert "didn't finish" in dialog._message.text()


def test_closing_mid_download_cancels_it(dialog: UpdateDialog, qtbot, made) -> None:
    qtbot.mouseClick(dialog._update, Qt.MouseButton.LeftButton)
    dialog.close()

    assert made[0].cancelled == 1


def test_skip_names_the_offered_version(dialog: UpdateDialog, qtbot) -> None:
    with qtbot.waitSignal(dialog.skip_requested) as blocker:
        qtbot.mouseClick(dialog._skip, Qt.MouseButton.LeftButton)
    assert blocker.args == [(0, 7, 0)]
    assert not dialog.isVisible()


def test_a_finished_install_is_passed_on(dialog: UpdateDialog, qtbot, made) -> None:
    qtbot.mouseClick(dialog._update, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(dialog.installed) as blocker:
        made[0].installed.emit(Path("/apps/lwsm.AppImage"))
    assert blocker.args == [Path("/apps/lwsm.AppImage")]
