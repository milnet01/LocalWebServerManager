"""The public half of the key that signs releases (LWSM-1548, ADR-0008).

Core module — no Qt (`docs/standards/coding-overrides.md § O1`).

The private half lives only on the author's PC, in
`~/.config/lwsm-release/signing.key`; `scripts/sign-release.py generate` makes
the pair and prints the line to paste below. **Until it is pasted the value is
empty, `public_key()` returns `None`, and no update is ever offered**
(`update.offer`): an app that cannot check a signature installs nothing.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# The raw 32-byte Ed25519 public key, base64.
RELEASE_PUBLIC_KEY_B64 = ""


def public_key() -> Ed25519PublicKey | None:
    """The committed key, or `None` while there is none or it does not parse.

    Read at call time, not import time, so a test can patch the constant.
    """
    if not RELEASE_PUBLIC_KEY_B64:
        return None
    try:
        raw = base64.b64decode(RELEASE_PUBLIC_KEY_B64, validate=True)
        return Ed25519PublicKey.from_public_bytes(raw)
    except (binascii.Error, ValueError):
        return None
