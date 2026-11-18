"""LWSM-1017 — the tray icon: its three entries, its click and its tooltip."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from lwsm.controller import ProjectStatus
from lwsm.tray import Tray, install_tray

pytestmark = pytest.mark.gui


@dataclass
class Row:
    status: ProjectStatus


class FakeController(QObject):
    """`rows()` and `projects_changed` are all the tray reads."""

    projects_changed = Signal()

    def __init__(self, statuses: list[ProjectStatus]) -> None:
        super().__init__()
        self.statuses = statuses

    def rows(self) -> list[Row]:
        return [Row(status) for status in self.statuses]


@dataclass
class Built:
    tray: Tray
    window: QWidget
    controller: FakeController
    shown: list[int]
    quits: list[int]


def build(qtbot, statuses: list[ProjectStatus] | None = None) -> Built:
    window = QWidget()
    qtbot.addWidget(window)
    controller = FakeController(statuses or [])
    shown: list[int] = []
    quits: list[int] = []

    def show_window() -> None:
        shown.append(1)
        window.show()

    tray = Tray(window, controller, QIcon(), show_window, lambda: quits.append(1))
    return Built(tray, window, controller, shown, quits)


def test_the_menu_offers_show_hide_and_quit_and_nothing_per_project(qtbot) -> None:
    """The user's 2026-08-03 call: no per-project submenu, three entries."""
    built = build(qtbot)
    texts = [a.text() for a in built.tray.menu.actions() if not a.isSeparator()]
    assert texts == ["&Show window", "&Hide window", "&Quit"]
    assert built.tray.icon.contextMenu() is built.tray.menu


def test_each_entry_does_what_it_says(qtbot) -> None:
    built = build(qtbot)
    built.window.show()
    qtbot.waitExposed(built.window)

    built.tray.hide_action.trigger()
    assert not built.window.isVisible(), "Hide window left the window shown"

    built.tray.show_action.trigger()
    assert built.shown == [1], "Show window did not bring the window forward"
    assert built.window.isVisible()

    built.tray.quit_action.trigger()
    assert built.quits == [1], "Quit did not reach the real quit"


def test_the_menu_enables_only_the_entry_that_changes_something(qtbot) -> None:
    built = build(qtbot)
    built.window.show()
    qtbot.waitExposed(built.window)
    built.tray.menu.aboutToShow.emit()
    assert not built.tray.show_action.isEnabled()
    assert built.tray.hide_action.isEnabled()

    built.window.hide()
    built.tray.menu.aboutToShow.emit()
    assert built.tray.show_action.isEnabled()
    assert not built.tray.hide_action.isEnabled()


def test_a_click_shows_a_hidden_window_and_hides_a_shown_one(qtbot) -> None:
    built = build(qtbot)
    click = QSystemTrayIcon.ActivationReason.Trigger

    built.tray.icon.activated.emit(click)
    assert built.shown == [1] and built.window.isVisible()

    built.tray.icon.activated.emit(click)
    assert not built.window.isVisible()

    # The context-menu reason opens the menu; it must not toggle the window.
    built.tray.icon.activated.emit(QSystemTrayIcon.ActivationReason.Context)
    assert built.shown == [1] and not built.window.isVisible()


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "No projects running"),
        ([ProjectStatus.STOPPED, ProjectStatus.RUNNING], "1 project running"),
        (
            [
                ProjectStatus.RUNNING,
                ProjectStatus.RUNNING_FOREIGN,
                ProjectStatus.RUNNING_WRONG_PORT,
                ProjectStatus.STARTING,
                ProjectStatus.UNKNOWN,
            ],
            "3 projects running",
        ),
    ],
)
def test_the_tooltip_counts_the_projects_running(qtbot, statuses, expected) -> None:
    """Every answering state counts; starting and unknown do not (§ O5)."""
    built = build(qtbot, statuses)
    name = QCoreApplication.applicationName()
    assert built.tray.icon.toolTip() == f"{name}\n{expected}"


def test_the_tooltip_follows_a_status_change(qtbot) -> None:
    built = build(qtbot, [ProjectStatus.STOPPED])
    built.controller.statuses = [ProjectStatus.RUNNING]
    built.controller.projects_changed.emit()
    assert built.tray.icon.toolTip().endswith("\n1 project running")


def test_a_language_change_resets_the_entries(qtbot) -> None:
    built = build(qtbot)
    built.tray.quit_action.setText("stale")
    QCoreApplication.sendEvent(built.window, QEvent(QEvent.Type.LanguageChange))
    assert built.tray.quit_action.text() == "&Quit"


def test_no_tray_means_no_icon(qtbot) -> None:
    """Without a tray the caller keeps closing as quitting."""
    window = QWidget()
    qtbot.addWidget(window)
    tray = install_tray(
        window,
        FakeController([]),
        QIcon(),
        lambda: None,
        lambda: None,
        available=False,
    )
    assert tray is None


def test_a_tray_is_shown_where_the_desktop_has_one(qtbot) -> None:
    window = QWidget()
    qtbot.addWidget(window)
    tray = install_tray(
        window,
        FakeController([]),
        QIcon(),
        lambda: None,
        lambda: None,
        available=True,
    )
    assert tray is not None
    assert tray.icon.isVisible()
