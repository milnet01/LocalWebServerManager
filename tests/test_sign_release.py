"""LWSM-1548 INV-18 — no private key is tracked, and `scripts/sign-release.py`
round-trips with the app's own check. A throwaway pair in a temporary home;
nothing here touches the author's real key or GitHub.
"""

from __future__ import annotations

import importlib.util
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
