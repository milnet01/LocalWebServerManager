"""Shared test setup.

`scripts/local-ci.sh` exports QT_QPA_PLATFORM=offscreen, but a bare `pytest`
does not — and a widget test that opens a real window on a developer's desktop
is the shape `docs/standards/testing.md § T6` forbids. So set it here when it
is unset, and leave an explicit choice alone.

`XDG_CONFIG_HOME` is pinned for the same reason and is stricter — unset, not
merely defaulted. Since LWSM-1031 `build_window` reads `settings.json`, so a
test that calls it would otherwise pick up the DEVELOPER'S OWN theme: three
tests in `test_mainwindow.py` call it with only `projects_path` pinned, and
they would pass or fail depending on which palette the author last chose in
the real app. `§ T1` calls that an injected seam's whole purpose; here the
seam is an environment variable, so it is pinned here rather than in each
test. A test that sets it itself still wins — `monkeypatch` is applied after
this fixture and undone before the next.

`XDG_SESSION_TYPE` is pinned for exactly that reason, and it was the third
variable to earn it (LWSM-1033). `placement.py` branches on it: a Wayland
session asks KWin to place the window and cannot read its own position back,
while every other session moves the window itself. This machine RUNS Wayland
and the CI runner has the variable unset, so an unpinned test asserting either
branch passes on one and fails on the other — the same two-machines-one-gate
split `CLAUDE.md` records for shellcheck versions and for the 24x24 target
floor. Pinned to `x11`, so the default is the branch that needs no compositor;
a test that wants the Wayland branch sets it itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path_factory, monkeypatch):
    """Point XDG_CONFIG_HOME at a directory this test owns.

    A fresh one per test, so a test that WRITES a config cannot be seen by the
    next. Nothing is created here: the point is that the path exists nowhere
    until something makes it, which is what a first run looks like.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")


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
def _restore_application_appearance():
    """Undo per-test writes to the application palette and font.

    A `QApplication` is created once per session, so both outlive the window
    that set them:

    - `MainWindow` sets the application **palette** (LWSM-1118), so the one
      test that builds a dark theme would otherwise tint every later test —
      and since most assertions here compare colours *relatively*, that would
      surface somewhere unrelated rather than as an obvious failure.
    - The LWSM-1119 test sets the application **font**, which would leave every
      later render at double size and silently change every text metric the
      suite measures.

    A no-op until a `QApplication` exists, which is the non-GUI tests.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before = (app.palette(), app.font()) if app is not None else None
    yield
    app = QApplication.instance()
    if app is not None and before is not None:
        app.setPalette(before[0])
        app.setFont(before[1])


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
