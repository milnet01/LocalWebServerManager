"""The update window: what changed, and Update now / Skip / Later (LWSM-1548).

UI module. Opened with `show()`, never `exec()`: a modal window would block the
project list, and a visible parentless one keeps `app.exec()` running after the
main window closes, so the relaunch's waiter would wait out its limit (spec
§ 4.5).

The release notes come from GitHub, so they are untrusted text. They render as
Markdown with raw HTML off, in a browser that loads no resource and opens no
link (spec INV-13).

It opens at the size the user last gave it, or large, and centred on the main
window (LWSM-1582). Centring is not this module's doing: `QDialog` centres
itself on its parent wherever a client may place windows, and KWin places a
transient window over its main window on Wayland (both measured 2026-11-18,
the second on a private KWin). Both centre the size the window has when it is
SHOWN, which is why the size is set in `__init__`.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from lwsm import update_fetch
from lwsm.update import Release, Version, format_version
from lwsm.update_fetch import UpdateInstaller

_NOTES_FEATURES = (
    QTextDocument.MarkdownFeature.MarkdownDialectGitHub
    | QTextDocument.MarkdownFeature.MarkdownNoHTML
)

# The first-open size, as fractions of the main window's (LWSM-1582): the size
# the user dragged it to in the 0.6.1 relaunch test, where that release's notes
# showed without scrolling. Fractions, not pixels, so it follows the main
# window and the text size (`coding-overrides.md § O7`).
WIDTH_OF_MAIN = 0.9
HEIGHT_OF_MAIN = 0.45


class ReleaseNotes(QTextBrowser):
    """Read-only notes that fetch nothing and open nothing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)

    def loadResource(self, type: int, name: QUrl | str) -> object:  # Qt names
        """Nothing, for every URL: an image in the notes is not loaded."""
        return None

    def set_notes(self, markdown: str) -> None:
        # `QTextBrowser.setMarkdown` takes no feature flags; the document does.
        self.document().setMarkdown(markdown, _NOTES_FEATURES)


MakeInstaller = Callable[[Release, str, QObject], UpdateInstaller]


class UpdateDialog(QDialog):
    """Offers one release; installs it on Update now."""

    skip_requested = Signal(object)  # the offered Version
    installed = Signal(object)  # the Path written
    # (width, height), once on closing, and only when the user changed the size
    # it opened at: a size nobody chose is not remembered, so the default keeps
    # following the main window until the user picks one.
    resized = Signal(object)

    def __init__(
        self,
        installed: Version,
        offered: Release,
        notes: list[Release],
        appimage: str,
        parent: QWidget | None = None,
        *,
        make_installer: MakeInstaller | None = None,
        size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(False)
        self._installed = installed
        self._offered = offered
        self._appimage = appimage
        self._make_installer: MakeInstaller = make_installer or (
            lambda release, path, owner: UpdateInstaller(release, path, owner)
        )
        self._installer: UpdateInstaller | None = None
        self._failure: tuple[str, str] | None = None

        layout = QVBoxLayout(self)
        self._heading = QLabel(self)
        self._heading.setWordWrap(True)
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._heading)
        self._notes = ReleaseNotes(self)
        layout.addWidget(self._notes, 1)
        self._notes_releases = notes
        self._message = QLabel(self)
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        self._message.hide()
        layout.addWidget(self._message)
        self._progress = QProgressBar(self)
        self._progress.hide()
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._update = QPushButton(self)
        self._skip = QPushButton(self)
        self._later = QPushButton(self)
        self._cancel = QPushButton(self)
        for button in (self._update, self._skip, self._later, self._cancel):
            # A QPushButton in a QDialog is auto-default, and the first becomes
            # the default when shown, so Enter would install.
            button.setAutoDefault(False)
            button.setDefault(False)
            buttons.addWidget(button)
        self._cancel.hide()
        buttons.insertStretch(0, 1)
        layout.addLayout(buttons)

        self._update.clicked.connect(self._start)
        self._skip.clicked.connect(self._skip_version)
        self._later.clicked.connect(self.close)
        self._cancel.clicked.connect(self._cancel_download)
        self._retranslate()
        self.resize(self._opening_size(size))
        self._opened_at = self.size()

    def _opening_size(self, remembered: tuple[int, int] | None) -> QSize:
        """The remembered size, or a share of the main window's; never larger
        than the screen, never smaller than the layout's minimum."""
        parent = self.parentWidget()
        if remembered is not None:
            want = QSize(*remembered)
        elif parent is not None:
            want = QSize(
                round(parent.width() * WIDTH_OF_MAIN),
                round(parent.height() * HEIGHT_OF_MAIN),
            )
        else:
            want = self.sizeHint()
        want = want.expandedTo(self.minimumSizeHint())
        screen = (parent or self).screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            want = want.boundedTo(screen.availableGeometry().size())
        return want

    def _retranslate(self) -> None:
        offered = format_version(self._offered.version)
        self.setWindowTitle(QCoreApplication.translate("UpdateDialog", "Update"))
        self._heading.setText(
            QCoreApplication.translate(
                "UpdateDialog", "Version %1 is available. You have %2."
            )
            .replace("%1", offered)
            .replace("%2", format_version(self._installed))
        )
        heading = QCoreApplication.translate("UpdateDialog", "Version %1")
        self._notes.set_notes(
            "\n\n".join(
                f"## {heading.replace('%1', format_version(release.version))}"
                f"\n\n{release.body}"
                for release in self._notes_releases
            )
        )
        self._notes.setAccessibleName(
            QCoreApplication.translate("UpdateDialog", "What's new")
        )
        self._progress.setAccessibleName(
            QCoreApplication.translate("UpdateDialog", "Download progress")
        )
        for button, text in (
            (self._update, QCoreApplication.translate("UpdateDialog", "&Update now")),
            (
                self._skip,
                QCoreApplication.translate("UpdateDialog", "&Skip this version"),
            ),
            (self._later, QCoreApplication.translate("UpdateDialog", "&Later")),
            (self._cancel, QCoreApplication.translate("UpdateDialog", "&Cancel")),
        ):
            button.setText(text)
            button.setAccessibleName(text.replace("&", ""))
        if self._failure is not None:
            self._message.setText(self._failure_text(*self._failure))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)

    def _start(self) -> None:
        self._failure = None
        self._message.hide()
        self._set_downloading(True)
        size = self._offered.appimage_size
        # Determinate from the asset's size; busy when GitHub gave none.
        self._progress.setRange(0, size)
        self._progress.setValue(0)
        installer = self._make_installer(self._offered, self._appimage, self)
        self._installer = installer
        installer.progress.connect(self._on_progress)
        installer.failed.connect(self._on_failed)
        installer.installed.connect(self._on_installed)
        installer.start()

    def _on_installed(self, target: object) -> None:
        self._installer = None
        self.installed.emit(target)

    def _on_progress(self, received: int, _expected: int) -> None:
        if self._progress.maximum() > 0:
            self._progress.setValue(min(received, self._progress.maximum()))

    def _on_failed(self, kind: str, detail: str) -> None:
        self._installer = None
        self._set_downloading(False)
        self._failure = (kind, detail)
        self._message.setText(self._failure_text(kind, detail))
        self._message.show()

    @staticmethod
    def _failure_text(kind: str, detail: str) -> str:
        if kind == update_fetch.INSTALL_UNVERIFIED:
            return QCoreApplication.translate(
                "UpdateDialog",
                "This download couldn't be proved to come from the app's "
                "author, so it was not installed.",
            )
        if kind == update_fetch.INSTALL_UNWRITABLE:
            return QCoreApplication.translate(
                "UpdateDialog", "The app can't replace itself in %1."
            ).replace("%1", detail)
        if kind == update_fetch.INSTALL_WRITE_FAILED:
            return QCoreApplication.translate(
                "UpdateDialog", "The update couldn't be written: %1"
            ).replace("%1", detail)
        return QCoreApplication.translate("UpdateDialog", "The download didn't finish.")

    def _set_downloading(self, downloading: bool) -> None:
        for button in (self._update, self._skip, self._later):
            button.setVisible(not downloading)
        self._cancel.setVisible(downloading)
        self._progress.setVisible(downloading)
        (self._cancel if downloading else self._update).setFocus()

    def _cancel_download(self) -> None:
        if self._installer is not None:
            self._installer.cancel()

    def _skip_version(self) -> None:
        self.skip_requested.emit(self._offered.version)
        self.close()

    def done(self, result: int) -> None:
        """Closing the window, by any route, stops a download in flight and
        hands on a size the user chose."""
        self._cancel_download()
        if self.size() != self._opened_at:
            self._opened_at = self.size()
            self.resized.emit((self.width(), self.height()))
        super().done(result)

    @property
    def offered(self) -> Release:
        return self._offered

    def is_downloading(self) -> bool:
        return self._installer is not None
