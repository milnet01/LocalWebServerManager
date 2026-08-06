"""LWSM-1005 INV-6, INV-7, INV-13, INV-15 — the row tells the truth, accessibly.

Headless under QT_QPA_PLATFORM=offscreen (`docs/standards/testing.md § T6`),
which conftest.py sets when it is unset.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from lwsm import mainwindow
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


# --- LWSM-1071: the AT tree is the surface a screen reader walks --------------


def accessible_children(widget) -> list[str]:
    """Every name Orca would find walking down from this widget.

    The row's own accessible name is not this surface. INV-6 asserted the name
    (correctly) while the glyph was exposed as a *child* named '●' — a test
    reading only the parent cannot see what a screen reader announces.
    """
    from PySide6.QtGui import QAccessible

    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None, "the row must be in the accessibility tree"
    return [
        interface.child(index).text(QAccessible.Text.Name)
        for index in range(interface.childCount())
    ]


@pytest.mark.parametrize(
    ("port", "listening"), [(5005, [5005]), (5005, []), (None, [])]
)
def test_the_glyph_is_never_a_child_of_the_accessibility_tree(
    qtbot, built, port, listening
) -> None:
    window, _ = window_for(qtbot, built, [record("a", port)], FakeProbe(*listening))
    row = rows_of(window)[0]

    names = accessible_children(row)
    for glyph in STATE_GLYPHS.values():
        assert glyph not in names, (
            f"a screen reader walking the row's children finds {glyph!r}: {names}"
        )


@pytest.mark.parametrize(
    ("port", "listening", "status"),
    [
        (5005, [5005], ProjectStatus.RUNNING),
        (5005, [], ProjectStatus.STOPPED),
        (None, [], ProjectStatus.UNKNOWN),
    ],
)
def test_the_glyph_is_still_painted_after_leaving_the_label(
    qtbot, built, port, listening, status
) -> None:
    """Removing the glyph from the AT tree must not remove it from the screen.

    `design.md § Accessibility` requires three redundant signals — word, colour
    and glyph — and every assertion above this one would pass just as happily if
    the glyph had simply been deleted. So this looks at the pixels.
    """
    window, _ = window_for(qtbot, built, [record("a", port)], FakeProbe(*listening))
    row = rows_of(window)[0]
    with qtbot.waitExposed(window):
        window.show()

    assert row._glyph_text == STATE_GLYPHS[status]
    with_glyph = row.grab().toImage()

    # Blank it and re-render: the difference IS the glyph. An exact-colour match
    # would only work for the filled '●' — '○' and '?' are antialiased strokes,
    # so no pixel in them equals the pure token colour.
    row._glyph_text = ""
    without_glyph = row.grab().toImage()

    changed = sum(
        1
        for y in range(with_glyph.height())
        for x in range(row._glyph_x, row._glyph_x + row._glyph_width)
        if with_glyph.pixel(x, y) != without_glyph.pixel(x, y)
    )
    assert changed > 0, (
        f"nothing is drawn in the glyph column for {status}: the glyph left the "
        f"accessibility tree and the screen with it"
    )


def test_the_state_word_is_still_coloured_from_the_theme(qtbot, built) -> None:
    """LWSM-1077 moved the colour from composed CSS to a generated style sheet
    selecting on a dynamic property. This pins that the sheet reaches the label
    at all; the two tests below pin that the right rule wins — and only those
    two can see a missing re-polish, which this one stays green through.
    """
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    label = rows_of(window)[0]._state
    assert label.text() == "running"

    themed = label.grab().toImage()

    # Strip the generated sheet and re-polish: the difference is what the theme
    # layer contributes. Comparing against a pure token colour instead does not
    # work — the word's strokes are antialiased, so no pixel equals it exactly.
    window.setStyleSheet("")
    label.style().unpolish(label)
    label.style().polish(label)
    unthemed = label.grab().toImage()

    assert themed != unthemed, (
        "the state word renders identically with and without the theme's style "
        "sheet — the generated rules are not reaching it"
    )


def shown(qtbot, window):
    with qtbot.waitExposed(window):
        window.show()
    return window


def render_with_common_text(label, text: str = "MMMM"):
    """Grab a state label with its text forced to a fixed string.

    Two statuses render different *words* as well as different colours, so
    comparing them directly proves nothing about colour. Forcing the same text
    leaves the state token as the only thing that can still differ.
    """
    label.setText(text)
    return label.grab().toImage()


def test_the_state_word_takes_its_colour_from_the_status(qtbot, built) -> None:
    running = shown(
        qtbot, window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))[0]
    )
    stopped = shown(
        qtbot, window_for(qtbot, built, [record("a", 5005)], FakeProbe())[0]
    )

    assert render_with_common_text(
        rows_of(running)[0]._state
    ) != render_with_common_text(rows_of(stopped)[0]._state), (
        "running and stopped render the same colour — the token never reached the word"
    )


def test_a_status_change_repaints_the_word_in_the_new_token(qtbot, built) -> None:
    """A row that *changed* into a state must render like one built in it.

    Compared against a row born in the target state, with the text forced the
    same, so neither the initial polish nor the differing word can carry the
    assertion.
    """
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    shown(qtbot, window)

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    changed = rows_of(window)[0]._state
    assert changed.text() == "stopped"

    born = shown(qtbot, window_for(qtbot, built, [record("a", 5005)], FakeProbe())[0])
    fresh = rows_of(born)[0]._state

    assert render_with_common_text(changed) == render_with_common_text(fresh), (
        "a row that changed into 'stopped' renders differently from one built "
        "as 'stopped' — the new state token was never applied"
    )


def test_the_row_exposes_only_its_three_cells(qtbot, built) -> None:
    """The count is the assertion that would have caught this: the row exposed
    four children, and setAccessibleName("") did not remove the fourth —
    QAccessibleDisplay falls back to QLabel::text() when the name is empty."""
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    names = accessible_children(rows_of(window)[0])

    assert names == ["running", "a", "port 5005"], names


# --- LWSM-1076: announced once per change, not once per second ----------------


@pytest.fixture
def announcements(monkeypatch):
    """Count the accessibility notifications the window raises.

    `QAccessible.installUpdateHandler` — the observing seam Qt provides — is not
    exposed in PySide6 (checked against the pinned 6.11.1), and AT-SPI is not
    reachable headless, so this stands in for it by counting the one call the
    window makes.
    """
    from PySide6.QtGui import QAccessible

    raised: list[object] = []

    class CountingAccessible:
        Event = QAccessible.Event

        @staticmethod
        def updateAccessibility(event) -> None:
            raised.append(event.object())

    monkeypatch.setattr(mainwindow, "QAccessible", CountingAccessible)
    return raised


def test_a_state_change_is_announced(qtbot, built, announcements) -> None:
    """`design.md § Accessibility` promises "a state change announces itself
    once". Qt does not notify AT-SPI when an accessible name changes, so
    setAccessibleName alone left that promise unimplemented."""
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    announcements.clear()

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert rows_of(window)[0]._state.text() == "stopped"
    assert len(announcements) == 1, (
        f"a state change raised {len(announcements)} announcements, expected 1"
    )


def test_an_unchanged_row_is_never_re_announced(qtbot, built, announcements) -> None:
    """The naive half of this fix turns a once-a-second no-op into a
    once-a-second re-announcement of every unchanged row — the failure INV-13
    exists to prevent, arriving by another route.

    `_sync_rows` calls `update_from` on every row on every signal, and
    `QLabel::setText` short-circuits where setStyleSheet and setAccessibleName
    do not. Spec § 4.4: "the changed rows' text and tokens only".
    """
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    row = rows_of(window)[0]
    announcements.clear()

    # Three ticks with nothing changing, driven through the row directly so the
    # controller's own signal suppression cannot be what makes this pass.
    for _ in range(3):
        row.update_from(controller.rows()[0])

    assert announcements == [], (
        f"{len(announcements)} announcements for a row that did not change"
    )


# --- LWSM-1074: a wide window must not scatter the row ------------------------

# LWSM-1032's own acceptance: "assert name, state, port and controls all fall
# inside a 600 px-wide window". A magnifier user pans; content that spreads to
# the window's full width turns reading one row into a sweep and a memory test,
# which design.md § Accessibility names as an anti-pattern outright.
READABLE_BAND_PX = 600


def test_the_row_stays_grouped_when_the_window_is_wide(qtbot, built) -> None:
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    window.resize(1400, window.height())
    qtbot.waitUntil(lambda: window.width() == 1400, timeout=2000)
    row = rows_of(window)[0]

    right_edge = row._port.geometry().right()
    assert right_edge <= READABLE_BAND_PX, (
        f"at {window.width()} px wide the port cell ends at x={right_edge}, "
        f"outside the {READABLE_BAND_PX} px band the row must stay inside"
    )


def test_the_cells_keep_their_order_and_do_not_overlap(qtbot, built) -> None:
    """Guards the fix from the obvious over-correction — collapsing the stretch
    could just as easily pile the cells on top of each other."""
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    window.resize(1400, window.height())
    qtbot.waitUntil(lambda: window.width() == 1400, timeout=2000)
    row = rows_of(window)[0]

    state, name, port = row._state, row._name, row._port
    assert state.geometry().right() <= name.geometry().left()
    assert name.geometry().right() <= port.geometry().left()


# --- LWSM-1070: focusable is not the same as showing where the focus is -------


def changed_pixels(first, second) -> int:
    assert first.size() == second.size(), "compare like with like"
    return sum(
        1
        for y in range(first.height())
        for x in range(first.width())
        if first.pixel(x, y) != second.pixel(x, y)
    )


def test_focus_is_visible_not_merely_held(qtbot, built) -> None:
    """The row is the only focusable widget in the app, and `QFrame` paints no
    focus indicator: `StyledPanel` never consults `State_HasFocus`.

    Asserted by rendering, because every property this could check instead —
    focusPolicy, hasFocus — was already true while the two images were
    byte-identical and Tab moved an invisible caret.
    """
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    # Both are context managers. Called bare they construct a waiter and wait
    # for nothing, which leaves the window inactive — and an inactive window
    # makes hasFocus() false, so the ring never paints and the test compares
    # two unfocused renders and passes for the wrong reason.
    with qtbot.waitExposed(window):
        window.show()
    with qtbot.waitActive(window):
        window.activateWindow()
    row = rows_of(window)[0]

    # Qt hands focus to the first focusable widget when the window is shown, so
    # the row already has it here. Without this the baseline grab is a *focused*
    # render, both images match, and the test reports "no ring" whether or not
    # one is painted.
    row.clearFocus()
    assert not row.hasFocus(), "the baseline must be an unfocused render"
    unfocused = row.grab().toImage()

    row.setFocus()
    assert row.hasFocus(), "the fixture must actually focus the row"
    focused = row.grab().toImage()

    difference = changed_pixels(unfocused, focused)
    assert difference > 0, (
        "focused and unfocused render identically — the focus ring is invisible"
    )
    # A handful of changed pixels would be an antialiasing artefact, not a ring.
    # The ring's own perimeter is roughly 2 * (w + h) * pen width.
    perimeter = 2 * (row.width() + row.height())
    assert difference > perimeter, (
        f"only {difference} pixels changed against a {perimeter}px perimeter — "
        f"too few to be a ring around the row"
    )


def test_the_focus_ring_grows_with_the_text(qtbot, built) -> None:
    """`§ O7`: sizes come from the text metric. A pixel constant would thin the
    ring to a hairline at LWSM-1032's 200 % text setting."""
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]
    small = row.focus_ring_width()

    font = row.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    row.setFont(font)

    assert row.focus_ring_width() > small


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


# --- LWSM-1082: the low-severity tail ------------------------------------------


class ShrinkingController:
    """Stands in for LWSM-1008's rescan: the record list can lose an entry."""

    def __init__(self, controller: ProjectController) -> None:
        self._controller = controller
        self.drop = False

    def rows(self):
        rows = self._controller.rows()
        return [] if self.drop else rows

    def __getattr__(self, item):
        return getattr(self._controller, item)


def test_a_removed_project_loses_its_row(qtbot, built) -> None:
    """`_sync_rows` only ever added. A project dropped from the list lingered
    showing its last observed state, which `§ O5` forbids."""
    controller = ProjectController([record("a", 5005)], FakeProbe(5005))
    built.append(controller)
    shrinking = ShrinkingController(controller)
    window = MainWindow(shrinking, Theme.default(), [])
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert len(rows_of(window)) == 1

    shrinking.drop = True
    window._sync_rows()

    assert rows_of(window) == [], "the row outlived the project"


def test_an_unmapped_state_does_not_crash_the_row(qtbot, built) -> None:
    """`STATE_GLYPHS[...]` and the theme's token map both ran inside a signal
    handler, so a state added by LWSM-1011 would be a UI crash rather than a
    missing glyph."""
    from enum import StrEnum

    from lwsm.controller import RowView

    class FutureStatus(StrEnum):
        # ADR-0004's seven states; LWSM-1011 splits the collapsed `running` into
        # these. A separate enum rather than a bare string, so the row is handed
        # the same shape a real new member would have.
        FOREIGN = "running (foreign)"

    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]

    invented = RowView(
        path=Path("/srv/a"),
        name="a",
        effective_port=5005,
        status=FutureStatus.FOREIGN,
    )
    row.update_from(invented)

    # The word still carries the state, which is the signal that must survive.
    assert row._state.text() == "running (foreign)"


def test_the_row_resizes_its_cells_when_the_font_grows(qtbot, built) -> None:
    """Computed once, the minimum widths would go stale under LWSM-1032's
    100-200 % text-size control."""
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]
    before = row._state.minimumWidth()

    font = row.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    row.setFont(font)

    assert row._state.minimumWidth() > before


# --- LWSM-1081: the strings are reachable by a translator ----------------------


def test_every_visible_string_goes_through_a_translator(qtbot, built) -> None:
    """`grep` for `.tr(` and `QCoreApplication.translate` across src/ returned
    zero hits, against `coding.md § 5.2`.

    Asserted by installing a translator and reading the rendered text, not by
    grepping for the call — a wrapper that is never consulted looks identical
    to one that is.
    """
    from PySide6.QtCore import QCoreApplication, QTranslator

    class Shouting(QTranslator):
        def translate(self, context, sourceText, disambiguation=None, n=-1) -> str:
            return sourceText.upper()

    translator = Shouting()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window, _ = window_for(qtbot, built, [record("a", None)], FakeProbe())
        row = rows_of(window)[0]

        assert row._state.text() == "UNKNOWN"
        assert row._port.text() == "NO PORT"
        assert window.windowTitle() == "LOCAL WEB SERVER MANAGER"

        with_port, _ = window_for(qtbot, built, [record("b", 5005)], FakeProbe(5005))
        # The number is interpolated into the translated string, not appended
        # to it — a translator must be able to move it.
        assert rows_of(with_port)[0]._port.text() == "PORT 5005"
    finally:
        app.removeTranslator(translator)


def test_the_untranslated_words_are_unchanged(qtbot, built) -> None:
    """With no translator installed the source strings render as before, so
    INV-6's announcement and every existing assertion still hold."""
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    assert rows_of(window)[0].accessibleName() == "running, a, port 5005"


def test_a_broken_translation_loses_the_number_not_the_window(qtbot, built) -> None:
    """A translation is data from outside the program.

    One that drops the placeholder must not take the row down — with
    `str.format` it raised KeyError inside a signal handler, which is
    LWSM-1082's crash class arriving by a new route.
    """
    from PySide6.QtCore import QCoreApplication, QTranslator

    class Broken(QTranslator):
        def translate(self, context, sourceText, disambiguation=None, n=-1) -> str:
            return "{port} %2 porta"  # every placeholder wrong

    translator = Broken()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
        assert rows_of(window)[0]._port.text() == "{port} %2 porta"
    finally:
        app.removeTranslator(translator)
