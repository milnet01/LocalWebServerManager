"""The tray icon: bring the window back, hide it, or quit (LWSM-1017).

UI module. Closing the window hides it here, so the app keeps watching while
nothing is on screen; the servers themselves outlive Quit too (ADR-0003).

**Deliberately no per-project menu** (user, 2026-08-03): a menu off a small
icon is a poor surface for a magnifier user, and the tray's job is bringing
the window back. A tooltip saying how many projects are running is all the
status the icon carries.

Nothing is reachable only from here (`design-accessibility.md`): the close
button hides, File > Quit quits, and opening the app again from the menu shows
a hidden window.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from lwsm.controller import RUNNING_STATES, ProjectController


class Tray(QObject):
    """The icon, its three-entry menu and its tooltip.

    `show_window` brings the window forward; the entry point passes the same
    routine a second launch uses, so both paths raise the window alike.
    `quit_app` is the real quit, which a closed window no longer is.
    """

    def __init__(
        self,
        window: QWidget,
        controller: ProjectController,
        icon: QIcon,
        show_window: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        # Parented to the window, which owns its lifetime (§ O6).
        super().__init__(window)
        self._window = window
        self._controller = controller
        self._show_window = show_window
        self.icon = QSystemTrayIcon(icon, self)
        # A tray icon does not own its menu, so the window does.
        self.menu = QMenu(window)
        self.show_action = self.menu.addAction("")
        self.show_action.triggered.connect(show_window)
        self.hide_action = self.menu.addAction("")
        self.hide_action.triggered.connect(window.hide)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("")
        self.quit_action.triggered.connect(quit_app)
        self.menu.aboutToShow.connect(self._sync_actions)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        controller.projects_changed.connect(self._update_tooltip)
        # The window hears LanguageChange; this object, not a widget, does not.
        window.installEventFilter(self)
        self._retranslate()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window and event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        return False

    def _retranslate(self) -> None:
        self.show_action.setText(
            QCoreApplication.translate("ProjectRow", "&Show window")
        )
        self.hide_action.setText(
            QCoreApplication.translate("ProjectRow", "&Hide window")
        )
        self.quit_action.setText(QCoreApplication.translate("ProjectRow", "&Quit"))
        self._update_tooltip()

    def say_still_running(self) -> None:
        """Tell the user, once, that a closed window left the app running.

        The window decides when: the first close that hides it, ever.
        """
        self.icon.showMessage(
            QCoreApplication.translate("ProjectRow", "Still running in the tray"),
            QCoreApplication.translate(
                "ProjectRow",
                "Local Web Server Manager keeps watching your projects. Click "
                "its tray icon to bring the window back, or choose Quit from "
                "the icon's menu to close it.",
            ),
        )

    def _sync_actions(self) -> None:
        """Offer only the entry that would change something."""
        shown = self._window.isVisible() and not self._window.isMinimized()
        self.show_action.setEnabled(not shown)
        self.hide_action.setEnabled(self._window.isVisible())

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """A click on the icon shows a hidden window and hides a shown one."""
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if self._window.isVisible() and not self._window.isMinimized():
            self._window.hide()
        else:
            self._show_window()

    def _update_tooltip(self) -> None:
        running = sum(row.status in RUNNING_STATES for row in self._controller.rows())
        if running == 0:
            status = QCoreApplication.translate("ProjectRow", "No projects running")
        elif running == 1:
            status = QCoreApplication.translate("ProjectRow", "1 project running")
        else:
            status = QCoreApplication.translate(
                "ProjectRow", "%1 projects running"
            ).replace("%1", QLocale().toString(running))
        self.icon.setToolTip(f"{QCoreApplication.applicationName()}\n{status}")


def install_tray(
    window: QWidget,
    controller: ProjectController,
    icon: QIcon,
    show_window: Callable[[], None],
    quit_app: Callable[[], None],
    *,
    available: bool | None = None,
) -> Tray | None:
    """Show a tray icon where the desktop has a tray, and say whether it did.

    Without a tray, closing the window must still quit: a hidden window with
    no icon would leave a running app the user cannot see or reach.
    `available` is the desktop's answer unless a caller gives one.
    """
    if available is None:
        available = QSystemTrayIcon.isSystemTrayAvailable()
    if not available:
        return None
    tray = Tray(window, controller, icon, show_window, quit_app)
    tray.icon.show()
    return tray
