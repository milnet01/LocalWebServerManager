"""LWSM-1548 — the self-update's requests, driven without a network.

INV-6, INV-10 and INV-11 of `docs/specs/LWSM-1548-appimage-self-update.md`.
Every handler is fed injected status, final URL and byte chunks; `start()` is
never called on a URL that would leave the machine.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from lwsm import update, update_fetch, update_key
from lwsm.update import Release
from lwsm.update_fetch import Download, UpdateCheck, UpdateInstaller

HTTPS = "https://github.invalid/asset"


class Outcome:
    """Every signal a `Download` emits, recorded."""

    def __init__(self, download: Download) -> None:
        self.finished: list[bytes] = []
        self.failed: list[str] = []
        download.finished.connect(self.finished.append)
        download.failed.connect(self.failed.append)


def _over_cap(download: Download, cap: int) -> None:
    """One byte over `cap`, in two chunks, with no Content-Length anywhere."""
    download.receive(b"a" * cap)
    download.receive(b"b")


# INV-10


@pytest.mark.parametrize(
    ("cap", "exact"),
    [(update_fetch.LIST_CAP, None), (update_fetch.SIGNATURE_CAP, None)],
    ids=["list", "signature"],
)
def test_a_read_one_byte_over_its_cap_is_aborted(cap: int, exact) -> None:
    download = Download(HTTPS, cap, exact=exact)
    seen = Outcome(download)

    _over_cap(download, cap)
    download.complete(error=False, status=200, final_url=HTTPS)

    assert seen.failed == [update_fetch.TOO_LARGE]
    assert seen.finished == []
    assert download._buffer == bytearray()


def test_the_caps_are_the_specified_sizes() -> None:
    assert update_fetch.LIST_CAP == 1024 * 1024
    assert update_fetch.SIGNATURE_CAP == 1024
    assert update_fetch.APPIMAGE_CAP == 256 * 1024 * 1024


def test_the_appimage_download_is_aborted_past_its_cap(monkeypatch) -> None:
    """The AppImage's own download, built by the installer. Its cap is shrunk
    for the test, because filling 256 MiB to prove one byte more is refused
    costs that much memory on every run; the value is pinned above."""
    monkeypatch.setattr(update_fetch, "APPIMAGE_CAP", 4096)
    monkeypatch.setattr(Download, "start", lambda self: None)
    installer = UpdateInstaller(_release(), "/nonexistent/app.AppImage")
    failures: list[tuple[str, str]] = []
    installer.failed.connect(lambda kind, detail: failures.append((kind, detail)))

    installer.on_signature(bytes(64))
    appimage = installer._active
    assert appimage is not None
    _over_cap(appimage, 4096)

    assert failures == [(update_fetch.INSTALL_INCOMPLETE, update_fetch.TOO_LARGE)]
    assert appimage._buffer == bytearray()


def test_a_signature_must_be_exactly_64_bytes() -> None:
    for size in (63, 65):
        download = Download(HTTPS, update_fetch.SIGNATURE_CAP, exact=64)
        seen = Outcome(download)
        download.receive(bytes(size))
        download.complete(error=False, status=200, final_url=HTTPS)
        assert seen.failed == [update_fetch.WRONG_SIZE]
        assert seen.finished == []
    download = Download(HTTPS, update_fetch.SIGNATURE_CAP, exact=64)
    seen = Outcome(download)
    download.receive(bytes(64))
    download.complete(error=False, status=200, final_url=HTTPS)
    assert seen.finished == [bytes(64)]


# INV-11


def test_an_http_url_never_reaches_a_request() -> None:
    download = Download("http://github.invalid/asset", update_fetch.LIST_CAP)
    seen = Outcome(download)

    download.start()

    assert seen.failed == [update_fetch.INSECURE]
    assert download._manager is None


def test_a_reply_that_ended_on_http_is_refused() -> None:
    download = Download(HTTPS, update_fetch.LIST_CAP)
    seen = Outcome(download)

    download.receive(b"[]")
    download.complete(
        error=False, status=200, final_url="http://objects.github.invalid/asset"
    )

    assert seen.failed == [update_fetch.INSECURE]
    assert seen.finished == []
    assert download._buffer == bytearray()


def test_an_error_or_a_non_200_status_is_unreachable() -> None:
    for error, status in ((True, None), (False, 403), (False, 404), (False, None)):
        download = Download(HTTPS, update_fetch.LIST_CAP)
        seen = Outcome(download)
        download.receive(b"[]")
        download.complete(error=error, status=status, final_url=HTTPS)
        assert seen.failed == [update_fetch.UNREACHABLE]
        assert seen.finished == []


# The release-list check's reading of a reply (feeds INV-15's wording).


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"not json", ("failed", update_fetch.CHECK_UNREADABLE)),
        (b'{"message": "rate limited"}', ("failed", update_fetch.CHECK_UNREADABLE)),
        (b"\xff\xfe", ("failed", update_fetch.CHECK_UNREADABLE)),
        (b"[]", ("found", [])),
    ],
    ids=["not-json", "object", "not-utf8", "empty-list"],
)
def test_the_check_reads_only_a_list(body: bytes, expected) -> None:
    check = UpdateCheck()
    got: list[tuple[str, object]] = []
    check.found.connect(lambda releases: got.append(("found", releases)))
    check.failed.connect(lambda why: got.append(("failed", why)))

    check.download.receive(body)
    check.download.complete(error=False, status=200, final_url=HTTPS)

    assert got == [expected]


def test_a_refused_check_is_unreachable() -> None:
    check = UpdateCheck()
    got: list[str] = []
    check.failed.connect(got.append)

    check.download.complete(error=True, status=403, final_url=HTTPS)

    assert got == [update_fetch.CHECK_UNREACHABLE]


# INV-6


def _release() -> Release:
    name = "https://github.invalid/LocalWebServerManager-0.6.0-x86_64.AppImage"
    return Release((0, 6, 0), "", name, name + ".sig", 10)


@pytest.fixture
def signing_key(monkeypatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setattr(
        update_key, "RELEASE_PUBLIC_KEY_B64", base64.b64encode(raw).decode()
    )
    return key


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "LocalWebServerManager-0.5.1-x86_64.AppImage"
    path.write_bytes(b"old app")
    path.chmod(0o755)
    return path


def _listing(*folders: str | Path) -> list[set[str]]:
    return [set(os.listdir(folder)) for folder in folders]


def test_nothing_reaches_the_disk_before_verify_returns(
    monkeypatch, signing_key, target: Path
) -> None:
    monkeypatch.setattr(Download, "start", lambda self: None)
    # A private temp folder, so parallel tests writing to /tmp cannot change
    # the listing; code using `tempfile` lands here all the same.
    private_tmp = target.parent / "tmp"
    private_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private_tmp))
    folders = (target.parent, tempfile.gettempdir())
    before = _listing(*folders)
    during: list[list[set[str]]] = []
    real_verify = update.verify

    def watching_verify(data: bytes, signature: bytes, version: str) -> None:
        during.append(_listing(*folders))
        real_verify(data, signature, version)

    monkeypatch.setattr(update, "verify", watching_verify)
    installer = UpdateInstaller(_release(), str(target))
    done: list[Path] = []
    installer.installed.connect(done.append)
    data = b"new app bytes"

    installer.on_signature(signing_key.sign(update.signed_message(data, "0.6.0")))
    installer.on_appimage(data)

    assert during == [before]
    assert done == [target]
    assert target.read_bytes() == data


def test_a_signature_that_fails_never_installs(
    monkeypatch, signing_key, target: Path
) -> None:
    monkeypatch.setattr(Download, "start", lambda self: None)
    installs: list[object] = []
    monkeypatch.setattr(update, "install", lambda *a: installs.append(a))
    installer = UpdateInstaller(_release(), str(target))
    failures: list[tuple[str, str]] = []
    installer.failed.connect(lambda kind, detail: failures.append((kind, detail)))
    data = b"new app bytes"

    other = Ed25519PrivateKey.generate()
    installer.on_signature(other.sign(update.signed_message(data, "0.6.0")))
    installer.on_appimage(data)

    assert failures == [(update_fetch.INSTALL_UNVERIFIED, "")]
    assert installs == []
    assert target.read_bytes() == b"old app"


def test_a_cancelled_download_installs_nothing(
    monkeypatch, signing_key, target: Path
) -> None:
    monkeypatch.setattr(Download, "start", lambda self: None)
    installer = UpdateInstaller(_release(), str(target))
    failures: list[tuple[str, str]] = []
    installer.failed.connect(lambda kind, detail: failures.append((kind, detail)))

    installer.start()
    installer.cancel()

    assert failures == [(update_fetch.INSTALL_INCOMPLETE, update_fetch.CANCELLED)]
    assert target.read_bytes() == b"old app"
