"""Shared test setup.

`scripts/local-ci.sh` exports QT_QPA_PLATFORM=offscreen, but a bare `pytest`
does not — and a widget test that opens a real window on a developer's desktop
is the shape `docs/standards/testing.md § T6` forbids. So set it here when it
is unset, and leave an explicit choice alone.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
