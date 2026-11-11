"""Sign a release's AppImage on this PC (LWSM-1548, ADR-0008).

Not part of the gate and not imported by the app. Releases are signed here,
after GitHub builds them, with a key that never leaves this PC: whoever got
into the GitHub account could otherwise sign a fake update.

Usage, from the repository root:

    uv run scripts/sign-release.py generate        # once, by the user
    uv run scripts/sign-release.py check-key       # 0 when the key matches
    uv run scripts/sign-release.py publish X.Y.Z   # after publishing vX.Y.Z

`generate` writes the private key to `~/.config/lwsm-release/signing.key`
(mode 600, never overwriting one) and prints the public key's base64, which
goes into `src/lwsm/update_key.py`. **Back the key up**: with it lost, every
installed AppImage refuses all later updates until its user downloads one by
hand.

`publish` waits for the tag's Release workflow, downloads its AppImage, signs
it for X.Y.Z, verifies the signature through `update.verify` against the
COMMITTED key, and uploads the `.sig` with `gh release upload --clobber`. Any
failure uploads nothing; a release with no `.sig` is offered to no one. Run it
again after moving a tag: the AppImage was rebuilt, and the `.sig` is replaced.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from lwsm import update, update_key

WORKFLOW = "release.yml"


def key_path() -> Path:
    return Path.home() / ".config" / "lwsm-release" / "signing.key"


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def generate(path: Path) -> str:
    """Write a new private key to `path`, refusing to overwrite; return the
    public key's base64."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    # O_EXCL: an existing key is never replaced, which would orphan every
    # installed copy.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    return public_b64(key)


def load_key(path: Path) -> Ed25519PrivateKey | None:
    """The private key at `path`, or `None` when it is missing or not one."""
    try:
        key = load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return None
    return key if isinstance(key, Ed25519PrivateKey) else None


def check_key(path: Path) -> bool:
    """Whether the key at `path` is the private half of the committed key."""
    key = load_key(path)
    committed = update_key.RELEASE_PUBLIC_KEY_B64
    return key is not None and bool(committed) and public_b64(key) == committed


def sign(key: Ed25519PrivateKey, data: bytes, version: str) -> bytes:
    """The release signature: the same message `update.verify` checks."""
    return key.sign(update.signed_message(data, version))


def _gh(*args: str, capture: bool = False) -> str:
    done = subprocess.run(  # noqa: S603 — fixed argv, no shell
        ["gh", *args],  # noqa: S607 — gh from PATH, as every release step uses
        check=True,
        text=True,
        capture_output=capture,
    )
    return done.stdout if capture else ""


def _release_run(tag: str) -> int:
    """The Release workflow run building `tag`."""
    runs = json.loads(
        _gh(
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--json",
            "databaseId,headBranch,event",
            "--limit",
            "20",
            capture=True,
        )
    )
    for run in runs:
        if run.get("headBranch") == tag and run.get("event") == "release":
            return int(run["databaseId"])
    raise SystemExit(f"sign-release: no {WORKFLOW} run found for {tag}")


def publish(version: str) -> None:
    if update.parse_version(version) is None or version.lower().startswith("v"):
        raise SystemExit(f"sign-release: {version!r} is not a version such as 0.6.0")
    key = load_key(key_path())
    if key is None or not check_key(key_path()):
        raise SystemExit("sign-release: the signing key is missing or does not match")
    tag = f"v{version}"
    asset = update.APPIMAGE_ASSET.format(version=version)
    _gh("run", "watch", str(_release_run(tag)), "--exit-status")
    # Beside the git directory, on the repository's own disk: /tmp is RAM on
    # the author's machine, and the AppImage is tens of megabytes.
    git_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="lwsm-sign-", dir=git_dir) as folder:
        _gh("release", "download", tag, "--pattern", asset, "--dir", folder)
        data = (Path(folder) / asset).read_bytes()
        signature = sign(key, data, version)
        # Against the COMMITTED key, through the app's own check: a signature
        # the shipped app would refuse is never uploaded.
        update.verify(data, signature, version)
        sig_path = Path(folder) / (asset + ".sig")
        sig_path.write_bytes(signature)
        _gh("release", "upload", tag, str(sig_path), "--clobber")
    print(f"sign-release: {asset}.sig uploaded to {tag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sign-release.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate", help="make the key pair, once")
    commands.add_parser("check-key", help="0 when the key matches the committed one")
    publish_parser = commands.add_parser("publish", help="sign a published release")
    publish_parser.add_argument("version")
    args = parser.parse_args(argv)

    if args.command == "generate":
        path = key_path()
        try:
            public = generate(path)
        except FileExistsError:
            print(f"sign-release: {path} already exists; not replacing it")
            return 1
        print(f"Private key written to {path}. Back it up.")
        print("Paste this into src/lwsm/update_key.py:")
        print(f'RELEASE_PUBLIC_KEY_B64 = "{public}"')
        return 0
    if args.command == "check-key":
        if check_key(key_path()):
            print("the signing key matches the committed public key")
            return 0
        print("the signing key is missing or does not match the committed public key")
        return 1
    publish(args.version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
