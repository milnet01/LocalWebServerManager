"""LWSM-1548 — the self-update's core: no Qt, no network, a throwaway key.

INV-1, INV-2, INV-3, INV-4, INV-5, INV-7, INV-8 and INV-9 of
`docs/specs/LWSM-1548-appimage-self-update.md`.
"""

from __future__ import annotations

import ast
import base64
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from lwsm import supervisor, update, update_key
from lwsm.update import (
    Release,
    UpdateInstallError,
    UpdateVerificationError,
    changelog,
    install,
    install_kind,
    offer,
    parse_version,
    releases_from_json,
    verify,
)


def _b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode()


@pytest.fixture
def signing_key(monkeypatch) -> Ed25519PrivateKey:
    """A throwaway pair, its public half patched in as the committed key."""
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", _b64(key))
    return key


def _release(version: str, *, signed: bool = True, body: str = "") -> Release:
    v = parse_version(version)
    assert v is not None
    base = f"https://example.invalid/LocalWebServerManager-{version}-x86_64.AppImage"
    return Release(v, body, base, base + ".sig" if signed else None, 1)


# INV-1


def test_install_kind_is_appimage_only_for_a_frozen_real_file(tmp_path: Path) -> None:
    real = tmp_path / "app.AppImage"
    real.write_bytes(b"x")
    assert install_kind(True, str(real)) == "appimage"
    assert install_kind(False, str(real)) == "checkout"
    assert install_kind(True, None) == "checkout"
    assert install_kind(True, str(tmp_path / "missing")) == "checkout"
    assert install_kind(True, str(tmp_path)) == "checkout"


# INV-2


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("0.6.0", (0, 6, 0)),
        ("v0.6.0", (0, 6, 0)),
        ("V10.0.12", (10, 0, 12)),
        ("0.6.0-rc.1", None),
        ("0.6", None),
        ("0.6.0.1", None),
        ("latest", None),
        ("0.¹.0", None),
        ("", None),
        ("vv0.6.0", None),
        ("0. 6.0", None),
    ],
)
def test_parse_version_accepts_three_ascii_numbers_only(tag, expected) -> None:
    assert parse_version(tag) == expected


# INV-3


def _entry(tag: str, **overrides) -> dict:
    version = tag.lstrip("v")
    name = f"LocalWebServerManager-{version}-x86_64.AppImage"
    entry = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": f"notes {version}",
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://github.invalid/{name}",
                "size": 1234,
            },
            {
                "name": name + ".sig",
                "browser_download_url": f"https://github.invalid/{name}.sig",
                "size": 64,
            },
        ],
    }
    entry.update(overrides)
    return entry


def test_releases_from_json_refuses_a_non_list() -> None:
    assert releases_from_json({"message": "API rate limit exceeded"}) is None
    assert releases_from_json("[]") is None
    assert releases_from_json(None) is None
    assert releases_from_json([]) == []


def test_releases_from_json_drops_every_bad_kind() -> None:
    older = _entry("v0.5.1")
    # An older version's file attached to a newer tag: matched by suffix alone
    # it would count, which is the trap the exact name closes.
    misnamed = _entry("v0.9.0")
    misnamed["assets"] = older["assets"]
    insecure = _entry("v0.8.0")
    for asset in insecure["assets"]:
        asset["browser_download_url"] = asset["browser_download_url"].replace(
            "https://", "http://"
        )
    data = [
        _entry("v0.6.0"),
        _entry("v0.7.0", draft=True),
        _entry("v0.7.1", prerelease=True),
        "not a dict",
        _entry("v1.0.0-rc.1"),
        _entry("v0.6.5", tag_name=7),
        _entry("v0.6.6", assets="nope"),
        _entry("v0.6.7", body=None),
        misnamed,
        insecure,
    ]
    found = {update.format_version(r.version): r for r in releases_from_json(data)}
    assert list(found) == ["0.9.0", "0.8.0", "0.6.7", "0.6.6", "0.6.0"]
    assert found["0.6.0"].appimage_url and found["0.6.0"].signature_url
    assert found["0.6.0"].appimage_size == 1234
    assert found["0.6.0"].body == "notes 0.6.0"
    assert found["0.9.0"].appimage_url is None
    assert found["0.9.0"].signature_url is None
    assert found["0.8.0"].appimage_url is None
    assert found["0.8.0"].signature_url is None
    assert found["0.6.6"].appimage_url is None
    assert found["0.6.7"].body == ""


def test_changelog_is_installed_exclusive_to_offered_inclusive() -> None:
    releases = [_release(v) for v in ("0.5.1", "0.8.0", "0.4.0", "0.6.0", "0.7.0")]
    got = changelog(releases, (0, 5, 1), (0, 7, 0))
    assert [r.version for r in got] == [(0, 7, 0), (0, 6, 0)]


# INV-4


def test_offer_takes_the_highest_signed_release(signing_key) -> None:
    installed = (0, 5, 1)
    unsigned_then_signed = [_release("0.7.0", signed=False), _release("0.6.0")]
    assert offer(unsigned_then_signed, installed, None).version == (0, 6, 0)
    assert offer(unsigned_then_signed, installed, (0, 6, 0)) is None
    newer = [_release("0.8.0"), _release("0.6.0")]
    assert offer(newer, installed, (0, 6, 0)).version == (0, 8, 0)
    both_signed = [_release("0.7.0"), _release("0.6.0")]
    assert offer(both_signed, installed, (0, 7, 0)) is None
    # A skip of a version no longer listed silences nothing older either.
    assert offer([_release("0.6.0")], installed, (0, 7, 0)).version == (0, 6, 0)
    assert offer([_release("0.5.1"), _release("0.4.0")], installed, None) is None


def test_offer_is_none_without_a_public_key(monkeypatch) -> None:
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", "")
    assert offer([_release("0.9.0")], (0, 5, 1), None) is None
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", "not base64!")
    assert offer([_release("0.9.0")], (0, 5, 1), None) is None


# INV-5


def _sign(key: Ed25519PrivateKey, data: bytes, version: str) -> bytes:
    return key.sign(update.signed_message(data, version))


def test_verify_accepts_only_the_exact_signed_bytes(signing_key) -> None:
    data = b"\x7fELF an AppImage"
    good = _sign(signing_key, data, "0.6.0")
    verify(data, good, "0.6.0")

    flipped_data = bytes([data[0] ^ 1]) + data[1:]
    flipped_sig = bytes([good[0] ^ 1]) + good[1:]
    cases = [
        (flipped_data, good, "0.6.0"),
        (data, flipped_sig, "0.6.0"),
        (data, good[:63], "0.6.0"),
        (data, good, "0.7.0"),
        (data, _sign(signing_key, data, "0.5.1"), "0.6.0"),
        (data, _sign(Ed25519PrivateKey.generate(), data, "0.6.0"), "0.6.0"),
    ]
    for args in cases:
        with pytest.raises(UpdateVerificationError):
            verify(*args)


def test_verify_refuses_everything_without_a_key(monkeypatch) -> None:
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", "")
    with pytest.raises(UpdateVerificationError):
        verify(b"x", bytes(64), "0.6.0")


# INV-7


def test_install_replaces_the_real_file_behind_a_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    real = tmp_path / "apps" / "LocalWebServerManager-0.5.1-x86_64.AppImage"
    real.parent.mkdir()
    real.write_bytes(b"old")
    real.chmod(0o755)
    link = tmp_path / "lwsm"
    link.symlink_to(real)

    made_in: list[object] = []
    real_mkstemp = update.tempfile.mkstemp

    def mkstemp(**kwargs):
        made_in.append(kwargs.get("dir"))
        return real_mkstemp(**kwargs)

    monkeypatch.setattr(update.tempfile, "mkstemp", mkstemp)
    assert install(b"new bytes", str(link)) == real
    # Beside the real file: a temp in /tmp makes `os.replace` raise EXDEV
    # wherever /tmp is another filesystem, which a test in /tmp cannot see.
    assert made_in == [real.parent]
    assert link.is_symlink()
    assert real.read_bytes() == b"new bytes"
    assert stat.S_IMODE(real.stat().st_mode) == 0o755
    assert sorted(p.name for p in real.parent.iterdir()) == [real.name]


def test_a_failed_replace_leaves_the_original_and_no_temp(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "app.AppImage"
    target.write_bytes(b"old")
    before = sorted(p.name for p in tmp_path.iterdir())

    def refuse(*_args) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(update.os, "replace", refuse)
    with pytest.raises(OSError):
        install(b"new", str(target))
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# INV-8


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a 0555 folder")
def test_an_unwritable_folder_is_refused_before_writing(tmp_path: Path) -> None:
    folder = tmp_path / "ro"
    folder.mkdir()
    target = folder / "app.AppImage"
    target.write_bytes(b"old")
    folder.chmod(0o555)
    try:
        with pytest.raises(UpdateInstallError) as raised:
            install(b"new", str(target))
        assert raised.value.folder == folder
        assert target.read_bytes() == b"old"
        assert [p.name for p in folder.iterdir()] == ["app.AppImage"]
    finally:
        folder.chmod(0o755)


def test_the_update_never_names_a_privilege_tool() -> None:
    source = Path(update.__file__).read_text(encoding="utf-8")
    strings = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not [s for s in strings if "sudo" in s or "pkexec" in s]


# INV-9


def test_relaunch_starts_the_waiter_in_its_own_scope(monkeypatch) -> None:
    prefix = ("/usr/bin/systemd-run", "--user", "--scope", "--")
    monkeypatch.setattr(supervisor, "scope_prefix", lambda env: prefix)
    seen: list[tuple[list[str], dict]] = []

    class Recorder:
        def __init__(self, argv, **kwargs) -> None:
            seen.append((argv, kwargs))

    monkeypatch.setattr(update.subprocess, "Popen", Recorder)
    calls: list[str] = []
    for name in ("execv", "execve", "execl", "execvp"):
        monkeypatch.setattr(update.os, name, lambda *a, n=name: calls.append(n))

    update.relaunch(Path("/home/u/app.AppImage"))

    [(argv, kwargs)] = seen
    assert argv == [
        *prefix,
        "/bin/sh",
        "-c",
        update.WAITER,
        "sh",
        str(os.getpid()),
        "/home/u/app.AppImage",
    ]
    assert kwargs["start_new_session"] is True
    assert kwargs["env"] == dict(os.environ)
    for stream in ("stdin", "stdout", "stderr"):
        assert kwargs[stream] == subprocess.DEVNULL
    assert calls == []


@pytest.mark.integration
def test_the_waiter_runs_the_target_only_after_the_pid_has_gone(
    tmp_path: Path,
) -> None:
    """Run for real against a child `sleep 0.5`. The child is not reaped while
    the waiter runs, so it is a zombie once it exits: that must count as gone.
    """
    marker = tmp_path / "ran"
    target = tmp_path / "target.sh"
    target.write_text(f"#!/bin/sh\necho done > '{marker}'\n")
    target.chmod(0o755)
    child = subprocess.Popen(["sleep", "0.5"])
    started = time.monotonic()
    try:
        subprocess.run(
            ["/bin/sh", "-c", update.WAITER, "sh", str(child.pid), str(target)],
            check=True,
            timeout=10,
        )
        elapsed = time.monotonic() - started
    finally:
        child.wait()
    assert elapsed >= 0.45
    assert marker.read_text() == "done\n"
