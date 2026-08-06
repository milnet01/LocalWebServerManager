"""LWSM-1005 INV-6, INV-7, INV-13, INV-15 — the row tells the truth, accessibly.

Headless under QT_QPA_PLATFORM=offscreen (`docs/standards/testing.md § T6`),
which conftest.py sets when it is unset.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from lwsm.__main__ import build_window
from lwsm.controller import ProjectController, ProjectStatus
from lwsm.mainwindow import STATE_GLYPHS, MainWindow
from lwsm.ports import PortProbe, PortSnapshot
from lwsm.registry import ProjectRecord
from lwsm.theme import Theme

pytestmark = pytest.mark.gui


class FakeProbe:
    def __init__(self, *ports: int) -> None:
        self.listening = set(ports)

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(frozenset(self.listening))


def record(name: str, port: int | None) -> ProjectRecord:
    return ProjectRecord(
        path=Path(f"/srv/{name}"), name=name, port=port, port_override=None
    )


@pytest.fixture
def built() -> Iterator[list[ProjectController]]:
    controllers: list[ProjectController] = []
    yield controllers
    for controller in controllers:
        controller.stop()


def window_for(qtbot, built, records, probe) -> tuple[MainWindow, ProjectController]:
    controller = ProjectController(records, probe)
    built.append(controller)
    window = MainWindow(controller, Theme.default(), [])
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    return window, controller


def rows_of(window: MainWindow) -> list:
    return list(window._rows.values())


# --- INV-6: state as a word, and no glyph in the accessible name --------------


@pytest.mark.parametrize(
    ("port", "listening", "expected"),
    [
        (5005, [5005], ProjectStatus.RUNNING),
        (5005, [], ProjectStatus.STOPPED),
        (None, [], ProjectStatus.UNKNOWN),
    ],
)
def test_state_is_a_word_not_only_colour(
    qtbot, built, port, listening, expected
) -> None:
    window, _ = window_for(qtbot, built, [record("a", port)], FakeProbe(*listening))
    row = rows_of(window)[0]

    # Strip colour and glyph and the state is still readable — the greyscale
    # test design.md § Accessibility makes the blunt version of.
    assert row._state.text() == str(expected)
    assert str(expected) in row.accessibleName()

    # A name built from the raw state cell would announce "black circle,
    # running, …" to a screen reader.
    for glyph in STATE_GLYPHS.values():
        assert glyph not in row.accessibleName(), row.accessibleName()


def test_accessible_name_never_says_port_none(qtbot, built) -> None:
    window, _ = window_for(qtbot, built, [record("a", None)], FakeProbe())
    name = rows_of(window)[0].accessibleName()

    assert "None" not in name
    assert name == "unknown, a, no port"


def test_accessible_name_carries_the_word_port(qtbot, built) -> None:
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    assert rows_of(window)[0].accessibleName() == "running, a, port 5005"


def test_a_row_is_keyboard_focusable(qtbot, built) -> None:
    from PySide6.QtCore import Qt

    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    assert rows_of(window)[0].focusPolicy() == Qt.FocusPolicy.StrongFocus


# --- INV-13: rows are updated, not rebuilt ------------------------------------


def test_focus_survives_a_status_change(qtbot, built) -> None:
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    row = rows_of(window)[0]
    row.setFocus()

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    # Identity, not equality: a rebuilt layout would give a new widget and drop
    # focus mid-read for a magnifier user.
    assert rows_of(window)[0] is row
    assert row._state.text() == "stopped"


# --- INV-7: the row follows a real socket, within 2 seconds -------------------


@pytest.mark.integration
def test_row_follows_a_real_socket(qtbot, built) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    try:
        controller = ProjectController([record("a", port)], PortProbe())
        built.append(controller)
        window = MainWindow(controller, Theme.default(), [])
        qtbot.addWidget(window)
        controller.start_polling()

        row = None
        qtbot.waitUntil(lambda: bool(rows_of(window)), timeout=2000)
        row = rows_of(window)[0]
        qtbot.waitUntil(lambda: row._state.text() == "running", timeout=2000)

        sock.close()
        qtbot.waitUntil(lambda: row._state.text() == "stopped", timeout=2000)
    finally:
        sock.close()


# --- INV-15: a RegistryError opens an empty window, it does not raise ---------


def test_registry_error_opens_an_empty_window(qtbot, built, tmp_path) -> None:
    # build_window rather than main: main blocks in app.exec(), so a test that
    # called it would never return.
    window, controller = build_window(tmp_path / "absent" / "projects.json")
    built.append(controller)
    qtbot.addWidget(window)

    assert rows_of(window) == []
    message = window.statusBar().currentMessage()
    assert "projects.json" in message, message


def test_notices_reach_the_status_bar(qtbot, built, tmp_path) -> None:
    import json

    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [
                    {"path": "relative", "name": "bad-one"},
                    {"path": "also-relative", "name": "bad-two"},
                    {"path": "/srv/ok", "name": "ok", "port": 5005},
                ],
            }
        ),
        encoding="utf-8",
    )
    window, controller = build_window(path)
    built.append(controller)
    qtbot.addWidget(window)

    message = window.statusBar().currentMessage()
    assert "bad-one" in message, message
    assert "(+1 more)" in message, message
    assert len(rows_of(window)) == 1, "the good record still renders"
