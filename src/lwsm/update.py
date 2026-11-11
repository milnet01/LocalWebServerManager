"""The AppImage's self-update, everything but the network (LWSM-1548).

Core module — no Qt (`docs/standards/coding-overrides.md § O1`). The requests
are `update_fetch.py`'s, the only module allowed to reach the internet; this
one decides what a reply means, proves a download came from the author, and
puts it in place.

The contract is `docs/specs/LWSM-1548-appimage-self-update.md`; the decision
behind it is ADR-0008.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from lwsm import update_key

Version = tuple[int, int, int]

APPIMAGE_ASSET = "LocalWebServerManager-{version}-x86_64.AppImage"
SIGNATURE_ASSET = APPIMAGE_ASSET + ".sig"
SIGNATURE_BYTES = 64  # an Ed25519 signature, raw
# Signed ahead of the bytes, with the version, so a genuine older AppImage and
# its `.sig` attached to a newer tag fail to verify (spec § 4.6).
SIGNED_PREFIX = b"LocalWebServerManager "


class UpdateVerificationError(Exception):
    """The download could not be proved to come from the author."""


class UpdateInstallError(Exception):
    """The running AppImage's folder cannot be written; nothing was."""

    def __init__(self, folder: Path) -> None:
        super().__init__(f"cannot write to {folder}")
        self.folder = folder


def install_kind(frozen: bool, appimage: str | None) -> str:
    """'appimage' when frozen and `appimage` names an existing regular file;
    'checkout' otherwise.

    Both halves, because `APPIMAGE` alone can be inherited: a checkout started
    from inside another AppImage's environment carries it too.
    """
    if frozen and appimage and os.path.isfile(appimage):
        return "appimage"
    return "checkout"


def parse_version(tag: str) -> Version | None:
    """'v0.6.0' / '0.6.0' -> (0, 6, 0). Exactly three dot-separated parts, each
    ASCII digits, one leading v or V allowed. Else None.

    `isascii()` as well as `isdigit()`, because `'¹'.isdigit()` is true.
    A pre-release tag such as `v1.0.0-rc.1` fails here and is never offered.
    """
    if tag[:1] in ("v", "V"):
        tag = tag[1:]
    parts = tag.split(".")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    major, minor, patch = (int(p) for p in parts)
    return major, minor, patch


def format_version(version: Version) -> str:
    """(0, 6, 0) -> '0.6.0'."""
    return ".".join(str(part) for part in version)


@dataclass(frozen=True)
class Release:
    version: Version
    body: str  # the release notes, Markdown; may be ""
    appimage_url: str | None  # browser_download_url of APPIMAGE_ASSET
    signature_url: str | None  # browser_download_url of SIGNATURE_ASSET
    appimage_size: int  # the asset's "size"; 0 when absent


def _asset_url(assets: object, name: str) -> tuple[str | None, int]:
    """The HTTPS download URL and size of the asset called exactly `name`."""
    if not isinstance(assets, list):
        return None, 0
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            return None, 0
        size = asset.get("size")
        return url, size if type(size) is int and size > 0 else 0
    return None, 0


def releases_from_json(data: object) -> list[Release] | None:
    """None when data is not a list. Otherwise every dict entry that is not a
    draft or prerelease and whose tag_name parses, highest version first. A
    malformed entry is dropped, never raised. An asset counts only when its
    name is the pattern filled with THIS release's version, and its URL starts
    with https://.

    A JSON object is GitHub's error shape (`{"message": ...}`), so reading it as
    an empty list would report "up to date" for a refused request.
    """
    if not isinstance(data, list):
        return None
    releases: list[Release] = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("draft") or entry.get("prerelease"):
            continue
        tag = entry.get("tag_name")
        version = parse_version(tag) if isinstance(tag, str) else None
        if version is None:
            continue
        name = APPIMAGE_ASSET.format(version=format_version(version))
        appimage_url, size = _asset_url(entry.get("assets"), name)
        signature_url, _ = _asset_url(entry.get("assets"), name + ".sig")
        body = entry.get("body")
        releases.append(
            Release(
                version=version,
                body=body if isinstance(body, str) else "",
                appimage_url=appimage_url,
                signature_url=signature_url,
                appimage_size=size,
            )
        )
    releases.sort(key=lambda r: r.version, reverse=True)
    return releases


def changelog(
    releases: Iterable[Release], installed: Version, offered: Version
) -> list[Release]:
    """installed < r.version <= offered, highest first."""
    return sorted(
        (r for r in releases if installed < r.version <= offered),
        key=lambda r: r.version,
        reverse=True,
    )


def offer(
    releases: Iterable[Release], installed: Version, skipped: Version | None
) -> Release | None:
    """The highest release above installed carrying both asset URLs, unless
    its version equals skipped. None when update_key.public_key() is None.

    Equality, never `<=`: skipping 0.6.0 must not silence 0.7.0.
    """
    if update_key.public_key() is None:
        return None
    for release in sorted(releases, key=lambda r: r.version, reverse=True):
        if release.version <= installed:
            return None
        if release.appimage_url and release.signature_url:
            return None if release.version == skipped else release
    return None


def signed_message(data: bytes, version: str) -> bytes:
    """What the signature covers: the prefix, the version, a newline, the bytes.

    `scripts/sign-release.py` signs this same message, so the two cannot drift.
    """
    return SIGNED_PREFIX + version.encode("ascii") + b"\n" + data


def verify(data: bytes, signature: bytes, version: str) -> None:
    """Return only when `signature` is the committed key's over `data` for
    `version`; raise `UpdateVerificationError` otherwise. The trust boundary.
    """
    key = update_key.public_key()
    if key is None:
        raise UpdateVerificationError("no release key is built into this app")
    if len(signature) != SIGNATURE_BYTES:
        raise UpdateVerificationError(
            f"the signature is {len(signature)} bytes, not {SIGNATURE_BYTES}"
        )
    try:
        key.verify(signature, signed_message(data, version))
    except InvalidSignature:
        raise UpdateVerificationError("the signature does not match") from None


def install(data: bytes, appimage: str) -> Path:
    """target = Path(os.path.realpath(appimage)). Raise UpdateInstallError,
    writing nothing, when os.access(target.parent, os.W_OK) is false. Write
    data to tempfile.mkstemp(prefix=".lwsm-update-", dir=target.parent),
    fchmod it to target's mode, fsync, os.replace(temp, target), fsync the
    folder. Any exception before os.replace unlinks the temp and leaves target
    untouched. Returns target.

    Beside the target, never in /tmp: `os.replace` across filesystems raises
    EXDEV. And never as root: an unwritable folder is reported, not escalated.
    """
    target = Path(os.path.realpath(appimage))
    folder = target.parent
    if not os.access(folder, os.W_OK):
        raise UpdateInstallError(folder)
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, temp = tempfile.mkstemp(prefix=".lwsm-update-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    folder_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(folder_fd)
    finally:
        os.close(folder_fd)
    return target


# $1 is this app's pid, $2 the new AppImage. Polls every 0.1 s for at most
# 60 s until the pid has gone — a zombie counts as gone, since its parent may
# not have reaped it yet — then execs the target. Waiting is what lets the new
# copy own the single-instance socket instead of handing itself back to us.
# The state is the field after the last ')' of /proc/<pid>/stat, because the
# command name before it may hold spaces.
WAITER = """\
i=0
while [ "$i" -lt 600 ]; do
    state=$(sed -n 's/.*) \\(.\\).*/\\1/p' "/proc/$1/stat" 2>/dev/null)
    case "$state" in ''|Z) break ;; esac
    sleep 0.1
    i=$((i + 1))
done
exec "$2"
"""


def relaunch(target: Path) -> None:
    """subprocess.Popen([*supervisor.scope_prefix(os.environ), '/bin/sh',
    '-c', WAITER, 'sh', str(os.getpid()), str(target)],
    start_new_session=True, env=dict(os.environ),
    stdin/stdout/stderr=DEVNULL). The caller then closes the main window
    through its normal close path.

    In a systemd scope of its own, as each server is: a desktop launch runs
    the app in a unit that kills its whole cgroup on exit, and a new session
    alone stays in it (ADR-0003, LWSM-1420). Never `os.exec*`: it cannot
    replace the busy mount (finbreak 0.1.2).
    """
    # Here, not at the top: `supervisor` imports `settings`, which imports
    # this module for `parse_version`.
    from lwsm import supervisor

    subprocess.Popen(  # noqa: S603 — a fixed argv; no shell parses the target
        [
            *supervisor.scope_prefix(os.environ),
            "/bin/sh",
            "-c",
            WAITER,
            "sh",
            str(os.getpid()),
            str(target),
        ],
        start_new_session=True,
        env=dict(os.environ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
