"""Shared test setup.

`scripts/local-ci.sh` exports QT_QPA_PLATFORM=offscreen, but a bare `pytest`
does not — and a widget test that opens a real window on a developer's desktop
is the shape `docs/standards/testing.md § T6` forbids. So set it here when it
is unset, and leave an explicit choice alone.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _reap_abandoned_probes():
    """Do not let the run end holding an abandoned pool (LWSM-1117).

    `~QThreadPool` joins its thread with **no timeout**, and that join happens
    after pytest has printed its report — so the cost is invisible to pytest's
    own number and shows up only as process wall time. Measured 2026-08-07:
    5.09 s reported against **7.67 s** wall, all 2.6 s of it here.

    2.6 s and not forever only because the fake probe that causes it carries a
    5 s timeout; against a probe that truly never returns the same shape hung
    the interpreter indefinitely. The entry point's escape is an `os._exit`,
    which a test process must never take — it would override pytest's exit code
    with this function's, which is exactly how LWSM-1100 produced a run
    truncated to 40 % and reported green. So the suite reaps instead.
    """
    yield
    from lwsm.controller import wait_for_abandoned_probes

    still_live = wait_for_abandoned_probes(5000)
    if still_live:  # pragma: no cover - a diagnosis, not a behaviour
        print(
            f"\n{still_live} abandoned probe pool(s) survived the run; "
            "the test that abandoned one did not release its fake probe.",
            file=sys.stderr,
        )


@pytest.fixture(autouse=True)
def _restore_application_palette():
    """Undo `MainWindow`'s application-palette change between tests (LWSM-1118).

    A `QApplication` is created once per session, so the palette `MainWindow`
    now sets on it outlives the window that set it. Without this, the one test
    that builds a dark theme would tint every test that ran after it — and
    since most assertions here are about *relative* colour, that would surface
    somewhere unrelated rather than as an obvious failure.

    A no-op until a `QApplication` exists, which is the non-GUI tests.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before = app.palette() if app is not None else None
    yield
    app = QApplication.instance()
    if app is not None and before is not None:
        app.setPalette(before)


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
