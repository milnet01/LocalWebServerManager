"""LWSM-1548 INV-18 — no private key is tracked, and `scripts/sign-release.py`
round-trips with the app's own check. A throwaway pair in a temporary home;
nothing here touches the author's real key or GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from lwsm import update, update_key
from lwsm.update import UpdateVerificationError

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "sign-release.py"


@pytest.fixture
def signer(monkeypatch, tmp_path: Path):
    """The script as a module, with HOME in a temporary folder."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    spec = importlib.util.spec_from_file_location("sign_release", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_private_key_is_tracked() -> None:
    tracked = (
        subprocess.run(
            ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
        )
        .stdout.decode()
        .split("\0")
    )
    assert not [name for name in tracked if name.endswith(".key")]
    pem = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
    holding = []
    for name in filter(None, tracked):
        path = REPO / name
        if path.is_file() and not path.is_symlink():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if pem.search(text):
                holding.append(name)
    assert holding == []


def test_a_signature_verifies_with_the_matching_key_only(signer, monkeypatch) -> None:
    path = signer.key_path()
    public = signer.generate(path)
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", public)
    data = b"an AppImage"

    signature = signer.sign(signer.load_key(path), data, "0.6.0")
    update.verify(data, signature, "0.6.0")

    other = signer.Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", signer.public_b64(other))
    with pytest.raises(UpdateVerificationError):
        update.verify(data, signature, "0.6.0")


def test_generate_never_overwrites_a_key(signer) -> None:
    path = signer.key_path()
    signer.generate(path)
    before = path.read_bytes()

    assert signer.main(["generate"]) == 1
    assert path.read_bytes() == before


def test_check_key_answers_without_printing_key_material(
    signer, monkeypatch, capsys
) -> None:
    # Missing file.
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", "")
    assert signer.main(["check-key"]) == 1

    public = signer.generate(signer.key_path())
    pem = signer.key_path().read_text()
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", public)
    assert signer.main(["check-key"]) == 0

    other = signer.Ed25519PrivateKey.generate()
    monkeypatch.setattr(update_key, "RELEASE_PUBLIC_KEY_B64", signer.public_b64(other))
    assert signer.main(["check-key"]) == 1

    printed = capsys.readouterr().out
    assert public not in printed
    assert pem.splitlines()[1] not in printed


def test_a_failed_key_write_leaves_no_partial_file(signer, monkeypatch) -> None:
    path = signer.key_path()

    def refuse(_fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(signer.os, "fsync", refuse)
    with pytest.raises(OSError):
        signer.generate(path)
    assert not path.exists()  # O_EXCL would otherwise block the retry


@pytest.mark.parametrize("version", ["00.6.0", "0.06.0", "v0.6.0", "0.6", "x"])
def test_publish_refuses_a_version_that_is_not_canonical(signer, version) -> None:
    with pytest.raises(SystemExit, match="not a version"):
        signer.canonical_version(version)


def test_publish_accepts_a_canonical_version(signer) -> None:
    assert signer.canonical_version("0.6.0") == "0.6.0"


def _fake_gh(published: str, run_lists: list[list[dict]]):
    """A `_gh` stand-in: the release's publish time, then each run listing in
    turn, the last repeated."""
    calls = iter(run_lists)
    last: list[list[dict]] = [run_lists[-1]]

    def fake(*args: str, capture: bool = False) -> str:
        if args[:2] == ("release", "view"):
            return published + "\n"
        if args[:2] == ("run", "list"):
            last[0] = next(calls, last[0])
            return json.dumps(last[0])
        raise AssertionError(f"unexpected gh call {args}")

    return fake


def _run(run_id: int, created: str) -> dict:
    return {
        "databaseId": run_id,
        "headBranch": "v0.6.1",
        "event": "release",
        "createdAt": created,
    }


def test_publish_never_signs_for_a_run_older_than_the_release(
    signer, monkeypatch
) -> None:
    """review-code 2026-11-18 L02-L2. A tag published again (unpublished to a
    draft, then published) still has its first run listed, finished. Taking
    that one watched nothing and signed the AppImage the new run was about to
    replace, so the uploaded .sig matched no file. Only a run created at or
    after the release's publish time counts, and one not listed yet is waited
    for."""
    monkeypatch.setattr("time.sleep", lambda _s: None)
    old = _run(1, "2026-11-18T10:00:00Z")
    new = _run(2, "2026-11-18T12:00:05Z")
    monkeypatch.setattr(
        signer, "_gh", _fake_gh("2026-11-18T12:00:00Z", [[old], [new, old]])
    )

    assert signer._release_run("v0.6.1") == 2


def test_publish_gives_up_when_no_run_for_this_publish_appears(
    signer, monkeypatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(
        signer,
        "_gh",
        _fake_gh("2026-11-18T12:00:00Z", [[_run(1, "2026-11-18T10:00:00Z")]]),
    )

    with pytest.raises(SystemExit, match="no release.yml run"):
        signer._release_run("v0.6.1")
