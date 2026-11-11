"""The self-update's requests: the release list and the two downloads (LWSM-1548).

Core module: `QtCore` and `QtNetwork`, never `QtWidgets`
(`docs/standards/coding-overrides.md § O1`). **The only module under
`src/lwsm/` that reaches the internet** (spec INV-12); `health.py` talks to
`localhost` alone.

Qt's network stack rather than `urllib`, because the bundle's OpenSSL looks for
CA certificates where the build container keeps them, and Qt's TLS backend reads
the host's own store (spec § 8).

Each download goes into memory and nowhere else. **Nothing reaches the disk
before it verifies, and the bytes verified are the bytes written** (spec § 4.6,
INV-6): `UpdateInstaller` hands the same `bytes` object to `update.verify` and
then to `update.install`.

The reply handlers are split from the Qt slots that feed them, so a test drives
them with injected status, final URL and byte chunks and no request leaves the
machine.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from lwsm import __version__, applog, update
from lwsm.update import Release

log = applog.get_logger(__name__)

RELEASES_URL = (
    "https://api.github.com/repos/milnet01/LocalWebServerManager/releases?per_page=30"
)
# GitHub refuses an API request with no User-Agent, and Qt sends none. It names
# the app and its version, nothing about the user.
USER_AGENT = f"LocalWebServerManager/{__version__}"

MIB = 1024 * 1024
LIST_CAP = 1 * MIB
SIGNATURE_CAP = 1024
APPIMAGE_CAP = 256 * MIB
# Counted by Qt from the last byte received, not from the start.
TRANSFER_TIMEOUT_MS = 30_000

# Why a `Download` failed. The caller turns these into words.
UNREACHABLE = "unreachable"  # network error, timeout, a status other than 200
TOO_LARGE = "too_large"  # more bytes than the cap
INSECURE = "insecure"  # the reply's final URL is not https://
WRONG_SIZE = "wrong_size"  # fewer or more bytes than the exact size required
CANCELLED = "cancelled"


class Download(QObject):
    """One GET into memory, capped on the bytes actually received.

    Its own `QNetworkAccessManager`, so no reply reaches another request's
    handler. `finished` and `failed` are each emitted at most once, and never
    both.
    """

    finished = Signal(bytes)
    failed = Signal(str)
    progress = Signal(int, int)  # received, expected (0 when unknown)

    def __init__(
        self,
        url: str,
        cap: int,
        *,
        exact: int | None = None,
        expected: int = 0,
        accept: str | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._cap = cap
        self._exact = exact
        self._expected = expected
        self._accept = accept
        self._buffer = bytearray()
        self._done = False
        self._reply: QNetworkReply | None = None
        self._manager: QNetworkAccessManager | None = None

    def start(self) -> None:
        if not self._url.startswith("https://"):
            self._fail(INSECURE)
            return
        self._manager = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(self._url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        if self._accept is not None:
            request.setRawHeader(b"Accept", self._accept.encode("ascii"))
        # Qt's default, stated: follows GitHub's redirect to its download host
        # and refuses one that drops to http://. The final URL is checked too.
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(TRANSFER_TIMEOUT_MS)
        reply = self._manager.get(request)
        self._reply = reply
        reply.readyRead.connect(lambda: self.receive(bytes(reply.readAll().data())))
        reply.finished.connect(self._on_finished)

    def cancel(self) -> None:
        """Stop and keep nothing; reports `CANCELLED` unless already done."""
        self._fail(CANCELLED)

    def _on_finished(self) -> None:
        reply = self._reply
        if reply is None:
            return
        self.receive(bytes(reply.readAll().data()))
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        self.complete(
            error=reply.error() != QNetworkReply.NetworkError.NoError,
            status=status if isinstance(status, int) else None,
            final_url=reply.url().toString(),
        )
        reply.deleteLater()

    def receive(self, chunk: bytes) -> None:
        """Take one chunk; abort the moment the total passes the cap."""
        if self._done or not chunk:
            return
        self._buffer += chunk
        if len(self._buffer) > self._cap:
            self._fail(TOO_LARGE)
            return
        self.progress.emit(len(self._buffer), self._expected)

    def complete(self, *, error: bool, status: int | None, final_url: str) -> None:
        """The reply has ended: hand the bytes on, or say why not."""
        if self._done:
            return
        if error or status != 200:
            self._fail(UNREACHABLE)
        elif not final_url.startswith("https://"):
            self._fail(INSECURE)
        elif self._exact is not None and len(self._buffer) != self._exact:
            self._fail(WRONG_SIZE)
        else:
            self._done = True
            data = bytes(self._buffer)
            self._buffer = bytearray()
            self.finished.emit(data)

    def _fail(self, why: str) -> None:
        if self._done:
            return
        self._done = True
        self._buffer = bytearray()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self.failed.emit(why)


# Why the release-list check failed, for `MainWindow`'s wording (spec § 4.4).
CHECK_UNREACHABLE = "unreachable"
CHECK_UNREADABLE = "unreadable"


class UpdateCheck(QObject):
    """Ask GitHub for the release list once."""

    found = Signal(list)  # list[update.Release], highest first
    failed = Signal(str)  # CHECK_UNREACHABLE or CHECK_UNREADABLE

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.download = Download(
            RELEASES_URL,
            LIST_CAP,
            accept="application/vnd.github+json",
            parent=self,
        )
        self.download.finished.connect(self.parse)
        self.download.failed.connect(
            lambda why: self.failed.emit(
                CHECK_UNREADABLE if why == TOO_LARGE else CHECK_UNREACHABLE
            )
        )

    def start(self) -> None:
        self.download.start()

    def parse(self, data: bytes) -> None:
        try:
            document = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            document = None
        releases = update.releases_from_json(document)
        if releases is None:
            self.failed.emit(CHECK_UNREADABLE)
        else:
            self.found.emit(releases)


# Why an install failed, for the dialog's wording (spec § 6).
INSTALL_INCOMPLETE = "incomplete"
INSTALL_UNVERIFIED = "unverified"
INSTALL_UNWRITABLE = "unwritable"
INSTALL_WRITE_FAILED = "write_failed"


class UpdateInstaller(QObject):
    """Download the `.sig`, then the AppImage, verify, then install.

    `failed` carries a kind and a detail: the folder for `INSTALL_UNWRITABLE`,
    the error for `INSTALL_WRITE_FAILED`, otherwise empty.
    """

    progress = Signal(int, int)
    installed = Signal(object)  # the Path written
    failed = Signal(str, str)

    def __init__(
        self, release: Release, appimage: str, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._release = release
        self._appimage = appimage
        self._signature: bytes | None = None
        self._active: Download | None = None
        self._ended = False

    def start(self) -> None:
        if not (self._release.signature_url and self._release.appimage_url):
            self._end_failed(INSTALL_INCOMPLETE, "")
            return
        download = Download(
            self._release.signature_url,
            SIGNATURE_CAP,
            exact=update.SIGNATURE_BYTES,
            parent=self,
        )
        download.finished.connect(self.on_signature)
        self._run(download)

    def cancel(self) -> None:
        if self._active is not None:
            self._active.cancel()

    def on_signature(self, signature: bytes) -> None:
        if self._ended:
            return
        self._signature = signature
        url = self._release.appimage_url
        if url is None:  # checked in start(); here for the type checker
            self._end_failed(INSTALL_INCOMPLETE, "")
            return
        download = Download(
            url,
            APPIMAGE_CAP,
            expected=self._release.appimage_size,
            parent=self,
        )
        download.progress.connect(self.progress)
        download.finished.connect(self.on_appimage)
        self._run(download)

    def on_appimage(self, data: bytes) -> None:
        if self._ended:
            return
        self._active = None
        signature = self._signature
        version = update.format_version(self._release.version)
        try:
            if signature is None:
                raise update.UpdateVerificationError("no signature was downloaded")
            update.verify(data, signature, version)
        except update.UpdateVerificationError as exc:
            log.warning("update %s refused: %s", version, exc)
            self._end_failed(INSTALL_UNVERIFIED, "")
            return
        try:
            target = update.install(data, self._appimage)
        except update.UpdateInstallError as exc:
            self._end_failed(INSTALL_UNWRITABLE, str(exc.folder))
            return
        except OSError as exc:
            log.warning("update %s not written: %s", version, exc)
            self._end_failed(INSTALL_WRITE_FAILED, exc.strerror or str(exc))
            return
        self._ended = True
        log.info("update %s installed at %s", version, target)
        self.installed.emit(target)

    def _run(self, download: Download) -> None:
        self._active = download
        download.failed.connect(lambda why: self._end_failed(INSTALL_INCOMPLETE, why))
        download.start()

    def _end_failed(self, kind: str, detail: str) -> None:
        if self._ended:
            return
        self._ended = True
        self._active = None
        self._signature = None
        self.failed.emit(kind, detail)
