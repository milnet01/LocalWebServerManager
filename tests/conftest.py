"""Shared test setup.

`scripts/local-ci.sh` exports QT_QPA_PLATFORM=offscreen, but a bare `pytest`
does not — and a widget test that opens a real window on a developer's desktop
is the shape `docs/standards/testing.md § T6` forbids. So set it here when it
is unset, and leave an explicit choice alone.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def dense_malformed_file(tmp_path: Path) -> Path:
    """A projects.json at `MAX_FILE_BYTES` holding as many rejectable elements
    as fit — the worst case LWSM-1115 bounds.

    The cheapest malformed element is a bare `1`, two bytes with its comma,
    yielding "not an object, skipped". Not contrived: nothing stops a user
    pointing the app at a JSON file that is not a project list at all.

    Shared rather than duplicated because two files assert against it from
    opposite ends — `test_registry.py` that the reason list is capped, and
    `test_mainwindow.py` that the cap actually reaches `build_window`, which is
    where the 8.7 s of no-window was spent.
    """
    from lwsm.registry import MAX_FILE_BYTES

    head, tail = '{"schema_version":1,"projects":[', "]}"
    count = (MAX_FILE_BYTES - len(head) - len(tail) + 1) // 2
    text = head + ",".join("1" for _ in range(count)) + tail
    while len(text.encode()) > MAX_FILE_BYTES:
        count -= 1
        text = head + ",".join("1" for _ in range(count)) + tail
    path = tmp_path / "projects.json"
    path.write_text(text, encoding="utf-8")
    return path
