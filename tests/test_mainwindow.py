"""LWSM-1005 INV-6, INV-7, INV-13, INV-15 — the row tells the truth, accessibly.

Headless under QT_QPA_PLATFORM=offscreen (`docs/standards/testing.md § T6`),
which conftest.py sets when it is unset.
"""

from __future__ import annotations

import dataclasses
import socket
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from lwsm import mainwindow
from lwsm.__main__ import build_window
from lwsm.controller import ProjectController, ProjectStatus
from lwsm.mainwindow import STATE_GLYPHS, MainWindow
from lwsm.ports import PortProbe, PortSnapshot
from lwsm.registry import (
    LauncherKind,
    LoadResult,
    ProjectRecord,
    RegistryError,
    RegistryMissing,
)
from lwsm.theme import Theme

pytestmark = pytest.mark.gui


class FakeProbe:
    def __init__(self, *ports: int) -> None:
        self.listening = set(ports)

    def snapshot(self) -> PortSnapshot:
        return PortSnapshot(frozenset(self.listening))


@dataclasses.dataclass(frozen=True)
class FakePortFinding:
    port: int


@dataclasses.dataclass(frozen=True)
class FakeDetected:
    """`scanner.DetectedProject` as `registry.merge` sees it (its Protocol)."""

    path: Path
    name: str
    kind: LauncherKind = LauncherKind.SHELL
    argv: tuple[str, ...] = ("./start.sh",)
    unit: str | None = None
    port: FakePortFinding | None = None


@dataclasses.dataclass(frozen=True)
class FakeScanResult:
    projects: tuple[FakeDetected, ...] = ()
    timed_out: bool = False
    unlistable_roots: tuple[Path, ...] = ()


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


def build_controller(built, records, probe) -> ProjectController:
    """A controller the `built` fixture will stop in teardown (§ T5, INV-16)."""
    controller = ProjectController(records, probe)
    built.append(controller)
    return controller


def window_for(qtbot, built, records, probe) -> tuple[MainWindow, ProjectController]:
    controller = build_controller(built, records, probe)
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


def ink_colours(label) -> Counter[str]:
    """The colours a label's *text* contributes, counted, background excluded.

    Two steps, and both were forced by a version of this that could not fail:

    - **Antialiasing is turned off first.** With it on, a one-character label
      rendered 0 pixels of a pure `#ff00ff` out of 119 and the ink spanned 40
      distinct colours including near-white subpixel fringe.
      `test_the_state_word_is_still_coloured_from_the_theme` records the same
      thing and dodges it by diffing two renders. Off, the ink is exactly one
      colour and the token can be asserted rather than approximated.
    - **The text is blanked and re-rendered to isolate the ink.** A first
      version took the nearest pixel of the whole grab and *passed against the
      unfixed code*, because the label's background was Fusion's light grey,
      which sat nearer a near-white dark-theme token than the black text did.
    """
    from PySide6.QtGui import QColor, QFont

    crisp = QFont(label.font())
    crisp.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    label.setFont(crisp)

    text = label.text()
    with_text = label.grab().toImage()
    label.setText("")
    without_text = label.grab().toImage()
    label.setText(text)
    return Counter(
        QColor(with_text.pixel(x, y)).name()
        for y in range(with_text.height())
        for x in range(with_text.width())
        if with_text.pixel(x, y) != without_text.pixel(x, y)
    )


def test_the_theme_reaches_the_cells_not_only_the_window(qtbot, built) -> None:
    """INV-24 — a palette set on the window reached the window and nothing in it.

    `setStyleSheet` installs `QStyleSheetStyle`, which re-resolves every
    descendant's palette from the **application** palette and discards the one
    just set on the widget. Verified on live widgets before the fix: `window`
    carried `WindowText=#1b1b1f` while `centralWidget`, the row and the name and
    port labels all carried Fusion's `#000000`.

    The light default hides it, which is why it survived three reviews: Fusion's
    black is *darker* than the `text` token, so contrast is accidentally better.
    A dark theme makes it visible at once — name and port rendered at 1.25:1 and
    1.27:1 against § T8's 4.5:1 floor, i.e. invisible, for a primary user who is
    partially sighted. So this test uses a dark theme, deliberately: under the
    default palette it cannot fail.

    Measured on 2026-08-07: the name cell's ink was **80 pixels of exactly
    `#000000`** before the fix and **80 pixels of exactly `#eef0ff`** after, so
    this asserts the token itself rather than a tolerance.
    """
    from dataclasses import replace

    dark = replace(
        Theme.default(),
        window="#16161a",
        base="#1e1e24",
        alt_base="#26262e",
        text="#eef0ff",
        is_dark=True,
    )
    controller = build_controller(built, [record("aaaa", 5005)], FakeProbe(5005))
    window = MainWindow(controller, dark, [])
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    with qtbot.waitExposed(window):
        window.show()

    ink = ink_colours(rows_of(window)[0]._name)

    assert ink, "the name cell rendered no text at all"
    assert set(ink) == {dark.text}, (
        f"the name cell's ink is {dict(ink)}, not the theme's text token "
        f"{dark.text} — the palette reached the window and not the cell"
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


def test_the_row_exposes_its_three_cells_and_its_three_buttons(qtbot, built) -> None:
    """The count is the assertion that would have caught this: the row exposed
    four children, and setAccessibleName("") did not remove the fourth —
    QAccessibleDisplay falls back to QLabel::text() when the name is empty.

    The three buttons joined the list with LWSM-1010 and are asserted **by
    exact name**, not merely counted. Each carries the project's name, because
    three rows of a bare "Start" leave a screen-reader user with three
    identical controls and no way to tell which is which (`§ O8`). The
    decorative glyph is still absent, which is what this test was written for.
    """
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    names = accessible_children(rows_of(window)[0])

    assert names == [
        "running",
        "a",
        "port 5005",
        "Start a",
        "Stop a",
        "Restart a",
    ], names
    assert not any(glyph in name for name in names for glyph in STATE_GLYPHS.values())


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


def test_a_status_change_requests_a_repaint(qtbot, built, monkeypatch) -> None:
    """The glyph is painted, so `update_from` has to mark the row dirty itself.

    **This asserts the call, not the pixels, and that is a deliberate retreat.**
    § 4.4 flags `self.update()` as a hazard because `grab()` repaints
    unconditionally, so no render-based test can see a missing repaint request
    (LWSM-1109). Trying anyway: a `paintEvent` counter stayed green with
    `self.update()` deleted, because the three labels change text on the same
    tick and the row is repainted regardless. In P02 there is no observable
    difference at all, so the mechanism is the only surface left — and a test
    that goes red on the mutation beats one that cannot.

    It stops being redundant at LWSM-1011, whose seven states allow a status to
    change while the word rendered for it does not: then nothing else dirties
    the row and only this call repaints the glyph.
    """
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    row = rows_of(window)[0]
    with qtbot.waitExposed(window):
        window.show()

    calls: list[int] = []
    real_update = row.update

    def spy(*args, **kwargs) -> None:
        calls.append(1)
        real_update(*args, **kwargs)

    # On the instance: `ProjectRow` is a Python class, so `self.update()`
    # resolves to this before QWidget.update.
    row.update = spy

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    assert calls, (
        "a status change did not request a repaint — at LWSM-1011 the painted "
        "glyph would keep its old colour until something else dirtied the row"
    )


def test_the_focus_ring_is_painted_in_the_accent_token(qtbot, built) -> None:
    """INV-17's two halves never met, so the ring's COLOUR was owned by nothing.

    One test asserts a contrast property of the `accent` *token*; the other
    asserts only that the focused and unfocused renders differ. Neither
    observes which colour the widget paints — so painting the ring in the
    *state* token left the whole suite green, and a palette whose state token
    sat at 2:1 would have shipped an invisible ring with INV-17 reporting
    green (LWSM-1105).

    QPainter antialiasing is off by default, so the ring's straight edges are
    the pen colour exactly and no tolerance is needed.
    """
    from PySide6.QtGui import QColor

    theme = Theme.default()
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    with qtbot.waitActive(window):
        window.activateWindow()
    row = rows_of(window)[0]

    row.setFocus()
    assert row.hasFocus(), "the fixture must actually focus the row"
    focused = row.grab().toImage()

    # The middle of the top edge: ring, never text, on every row width.
    painted = QColor(focused.pixel(row.width() // 2, 0))

    assert painted == theme.focus_ring_color(), (
        f"the ring is painted {painted.name()}, not the accent token "
        f"{theme.focus_ring_color().name()}"
    )
    # Named explicitly, because the state token is what a plausible edit would
    # reach for and it is the mutation that left every test green.
    assert painted != theme.state_color(ProjectStatus.RUNNING), (
        "the ring is painted in the state token"
    )


def glyph_column_pixels(row, glyph: str = "●") -> list[int]:
    """The glyph column's pixels, with the glyph text forced to a constant.

    Two statuses paint different *shapes* as well as different colours, so
    comparing them directly proves nothing about colour — the same reasoning
    as `render_with_common_text` one level out. Forcing one glyph leaves the
    state token as the only thing that can still differ.
    """
    row._glyph_text = glyph
    row.update()
    image = row.grab().toImage()
    return [
        image.pixel(x, y)
        for y in range(image.height())
        for x in range(row._glyph_x, row._glyph_x + row._glyph_width)
    ]


def test_the_painted_glyph_takes_the_matching_state_token(qtbot, built) -> None:
    """§ 4.4 requires the glyph to take "the matching state token's colour",
    and colour is one of `design.md § Accessibility`'s three redundant signals.

    Nothing checked it: INV-19 checks the glyph is *drawn* and INV-23 checks
    only the *word*, so painting every glyph in the `stopped` token regardless
    of state left the whole suite green (LWSM-1105).

    One row driven through two statuses by the real poll path, so the geometry,
    the font and the glyph text are all identical and the colour is the only
    remaining variable.
    """
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    assert row._view.status is ProjectStatus.RUNNING
    running = glyph_column_pixels(row)

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert row._view.status is ProjectStatus.STOPPED
    stopped = glyph_column_pixels(row)

    assert running != stopped, (
        "the glyph renders identically for running and stopped with the same "
        "glyph text — it is not taking the state token's colour"
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


def test_an_application_font_change_reflows_an_existing_row(qtbot, built) -> None:
    """INV-25 — `§ O8` clause 4's 200 % path, by the route a real control uses.

    `_apply_text_metrics`'s docstring says it is re-applied on every font change
    "so LWSM-1032's 100-200 % text-size control does not leave these stale". It
    was not: measured on 2026-08-07, `QApplication.setFont()` and
    `MainWindow.setFont()` each produced **zero** calls to it and left the row's
    metrics unchanged, because `setStyleSheet` makes QStyleSheetStyle resolve a
    font onto every descendant — which marks it explicitly set, so neither the
    `FontChange` event nor the new value propagates. Isolated against a bare
    `QWidget` tree: 1 `FontChange` without a style sheet, 0 with one.

    Only `row.setFont()` worked, and all three tests covering the 200 % path
    used exactly that — so the suite reported the path as covered while the
    route a text-size control actually takes was dead. This test drives the
    **application** font for that reason; driving the row's would restore the
    same blind spot.
    """
    from PySide6.QtWidgets import QApplication

    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]
    before = (row._glyph_width, row.layout().contentsMargins().left())

    bigger = QApplication.font()
    bigger.setPointSizeF(bigger.pointSizeF() * 2)
    QApplication.setFont(bigger)
    qtbot.wait(1)

    after = (row._glyph_width, row.layout().contentsMargins().left())
    assert after != before, (
        f"the row's metrics are unchanged at {before} after the application "
        f"font doubled — the reflow never reached it"
    )
    assert row._glyph_width > before[0], (
        f"the glyph column shrank or held at {after[0]} from {before[0]}"
    )


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


def test_a_dense_malformed_file_does_not_flood_the_log_before_the_window(
    qtbot, built, dense_malformed_file, caplog
) -> None:
    """The delivery half of LWSM-1115: the cap must reach `build_window`.

    `build_window` emits one `log.warning` per reason and runs *before*
    `window.show()`, so an unbounded list is not merely a large log — it is that
    many seconds of no window, with nothing on screen to interrupt. Measured at
    the file-size cap before the fix: 524,271 records, 28.7 MB, 8.7 s.

    Asserting the record count as well as the clock, because the count is
    deterministic and the clock is not: a loaded machine can make any wall-time
    bound flaky, so the time here is a smoke bound on the order of magnitude
    (seconds, not tens of seconds) and the count is the real assertion.
    """
    import logging
    import time

    with caplog.at_level(logging.WARNING, logger="lwsm"):
        start = time.perf_counter()
        window, controller = build_window(dense_malformed_file)
        elapsed = time.perf_counter() - start
    built.append(controller)
    qtbot.addWidget(window)

    notices = [r for r in caplog.records if "project list:" in r.getMessage()]
    assert len(notices) <= 101, f"{len(notices):,} log records for one bad file"
    assert elapsed < 5.0, f"build_window took {elapsed:.1f} s before showing a window"


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

    def __init__(
        self, controller: ProjectController, keep_from: int | None = None
    ) -> None:
        """`drop` removes every row, or every row before `keep_from`."""
        self._controller = controller
        self.drop = False
        self._keep_from = keep_from

    def rows(self):
        rows = self._controller.rows()
        if not self.drop:
            return rows
        return [] if self._keep_from is None else rows[self._keep_from :]

    def __getattr__(self, item):
        return getattr(self._controller, item)


def test_a_removed_project_loses_its_row(qtbot, built) -> None:
    """`_sync_rows` only ever added. A project dropped from the list lingered
    showing its last observed state, which `§ O5` forbids.

    Asserts the widget is gone from the SCREEN, not from `_rows`. Reading the
    dict is satisfied by the `pop()` alone: deleting both `removeWidget` and
    `deleteLater` left the previous shape of this test green (LWSM-1106).
    """
    controller = build_controller(built, [record("a", 5005)], FakeProbe(5005))
    shrinking = ShrinkingController(controller)
    window = MainWindow(shrinking, Theme.default(), [])
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert len(rows_of(window)) == 1
    widget = rows_of(window)[0]
    with qtbot.waitExposed(window):
        window.show()

    shrinking.drop = True
    window._sync_rows()

    assert rows_of(window) == [], "the row outlived the project"
    # `QLayout.removeWidget` neither hides nor reparents, and `deleteLater`
    # only lands on a DeferredDelete pass — so the widget was still visible,
    # still parented and still occupying its rectangle after processEvents().
    assert not widget.isVisible(), "the removed row is still on screen"
    assert widget.parent() is None, "the removed row is still in the window"


def test_a_removed_row_does_not_overlap_the_row_that_replaces_it(qtbot, built) -> None:
    """The surviving row moves up INTO the removed row's rectangle.

    Verified with two rows, dropping the first: the removed row stayed at
    `QRect(9, 9, 182, 37)` and the survivor moved into it, so the two
    geometries intersected. Sub-frame in production because the loop spins
    before the next paint — but that is an undocumented dependence on Qt's
    delete ordering, and one `setParent(None)` removes it (LWSM-1106).
    """
    controller = build_controller(
        built, [record("a", 5005), record("b", 5006)], FakeProbe(5005)
    )
    # Drops the FIRST row, so the survivor moves up into its rectangle.
    shrinking = ShrinkingController(controller, keep_from=1)
    window = MainWindow(shrinking, Theme.default(), [])
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    assert len(rows_of(window)) == 2
    removed = rows_of(window)[0]
    with qtbot.waitExposed(window):
        window.show()
    vacated = removed.geometry()

    shrinking.drop = True
    window._sync_rows()
    # `activate()` rather than a loop spin: the re-layout has to have happened
    # for the survivor to have moved, but spinning would run the
    # DeferredDelete pass and destroy the very widget under test.
    window._rows_layout.activate()
    survivor = rows_of(window)[0]

    # The precondition, asserted rather than assumed: the survivor really does
    # move into the space the removed row held, so a row left visible and
    # parented is drawn on top of it. Without this, the two assertions below
    # could pass in a layout where nothing ever moved.
    assert survivor.geometry().intersects(vacated), (
        f"the survivor at {survivor.geometry()} did not move into the vacated "
        f"{vacated} — this test is no longer exercising the overlap"
    )
    # Not a rect comparison: once unparented, the removed widget keeps its old
    # rectangle in its own coordinate space, so comparing the two says nothing.
    # Hidden and unparented is what makes it undrawable in this window.
    assert not removed.isVisible(), "the removed row is still on screen"
    assert removed.parent() is None, "the removed row is still in the window"


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
    state_before = row._state.minimumWidth()
    # The port cell too: `_port.setMinimumWidth` could be deleted outright and
    # the suite stayed green, because only the state cell was asserted
    # (LWSM-1109).
    port_before = row._port.minimumWidth()

    font = row.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    row.setFont(font)

    assert row._state.minimumWidth() > state_before
    assert row._port.minimumWidth() > port_before


def glyph_ink_bounds(row) -> tuple[int, int]:
    """The leftmost and rightmost columns the glyph actually paints.

    Blank the glyph and re-render: the difference IS the glyph, which is the
    same trick `test_the_glyph_is_still_painted_after_leaving_the_label` uses
    and for the same reason — '○' and '?' are antialiased strokes, so no pixel
    in them equals the pure token colour.

    Scanned across the **whole row**, never across the reserved column: a
    count scoped to the column cannot see that the column is the problem.
    """
    with_glyph = row.grab().toImage()
    kept, row._glyph_text = row._glyph_text, ""
    without_glyph = row.grab().toImage()
    row._glyph_text = kept

    columns = [
        x
        for y in range(with_glyph.height())
        for x in range(with_glyph.width())
        if with_glyph.pixel(x, y) != without_glyph.pixel(x, y)
    ]
    assert columns, "the glyph painted nothing at all"
    return min(columns), max(columns)


def test_the_glyph_is_not_clipped_when_the_text_size_doubles(qtbot, built) -> None:
    """`coding.md § O8` clause 4: reflows at 200 % text size without clipping.

    `_glyph_width` and the widened left content margin were computed once in
    `__init__`, and `changeEvent`'s `FontChange` branch recomputed only the
    state and port minimum widths — while `_apply_text_metrics`'s own
    docstring claimed it kept sizes fresh. `paintEvent` draws into
    `QRect(self._glyph_x, 0, self._glyph_width, ...)` and `drawText` **clips**
    to that rectangle.

    Measured before the fix: 13 px reserved against 14 px needed at 200 % and
    22 px at 300 %, with the ink running to both edges of the reserved
    rectangle at both scales (unclipped at 100 %, ink [14, 20] inside a
    [11, 24) column). This is the setting the people who need the glyph will
    be using.
    """
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]
    shown(qtbot, window)

    font = row.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    row.setFont(font)

    left, right = glyph_ink_bounds(row)
    last_column = row._glyph_x + row._glyph_width - 1

    # Strictly inside, not merely overlapping: clipped ink runs to the
    # rectangle's own edges, which is precisely what 200 % produced.
    assert row._glyph_x < left <= right < last_column, (
        f"the glyph paints columns [{left}, {right}] in a reserved column of "
        f"[{row._glyph_x}, {last_column}] — it is being clipped at 200 % text"
    )


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
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
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


def test_a_translator_installed_later_reaches_an_existing_row(qtbot, built) -> None:
    """§ 4.4's stated reason for translating at call time was untrue as written.

    There was no `LanguageChange` branch, and LWSM-1076's equality guard
    suppresses the only path that would re-render — so a row built *before* the
    translator rendered untranslated forever while one built after rendered
    translated. Every existing translator test installs first and so cannot see
    it (LWSM-1107).
    """
    from PySide6.QtCore import QCoreApplication, QTranslator

    class Shouting(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            return sourceText.upper()

    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]
    assert row._state.text() == "running", "precondition: built untranslated"

    translator = Shouting()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        # The event is delivered by hand, and that is a real limit on what this
        # test proves. Measured against the pinned PySide6 6.11.1: with the
        # event loop running and the window the only registered top-level
        # widget, `installTranslator` returned True and Qt still did **not**
        # post `LanguageChange` to it — while a bare `QMainWindow` in the same
        # shape did receive it. So this pins the handler, which is the half
        # this project owns; it does not pin Qt's broadcast.
        #
        # No user-visible impact in P02, which has no language switcher. A
        # switcher (LWSM-1032's neighbourhood) installs the translator itself
        # and can send this same event, so the mechanism is what it needs.
        QApplication.sendEvent(window, QEvent(QEvent.Type.LanguageChange))

        assert row._state.text() == "RUNNING", (
            "a row built before the translator was installed never retranslated"
        )
        assert row._port.text() == "PORT 5005"
        assert window.windowTitle() == "LOCAL WEB SERVER MANAGER"
        # The announcement must follow the words a listener actually hears.
        assert row.accessibleName() == "RUNNING, a, PORT 5005"
    finally:
        app.removeTranslator(translator)


def test_the_status_bar_summary_is_translatable(qtbot, built) -> None:
    """`f" (+{len(notices) - 1} more)"` was built with an f-string and never
    reached a translator, so the status bar read the same in every language —
    against § 4.4's "**every** user-visible string in this file" (LWSM-1107).
    """
    from PySide6.QtCore import QCoreApplication, QTranslator

    class Shouting(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            return sourceText.upper()

    translator = Shouting()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window = MainWindow(
            build_controller(built, [record("a", 5005)], FakeProbe(5005)),
            Theme.default(),
            ["first notice", "second notice", "third notice"],
        )
        qtbot.addWidget(window)
        assert "MORE" in window.statusBar().currentMessage(), (
            window.statusBar().currentMessage()
        )
    finally:
        app.removeTranslator(translator)


def test_every_translated_string_uses_one_context(qtbot, built) -> None:
    """§ 4.4: one context for the whole file, so a translator has one place to
    look. `self.tr("Local Web Server Manager")` resolved under `"MainWindow"`,
    not the `_TR_CONTEXT = "ProjectRow"` the file declares (LWSM-1107)."""
    from PySide6.QtCore import QCoreApplication, QTranslator

    seen: list[str] = []

    class Recording(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            seen.append(context)
            return sourceText

    translator = Recording()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    finally:
        app.removeTranslator(translator)

    assert seen, "no string was routed through a translator at all"
    assert set(seen) == {mainwindow._TR_CONTEXT}, sorted(set(seen))


def test_a_broken_translation_loses_the_number_not_the_window(qtbot, built) -> None:
    """A translation is data from outside the program.

    One that drops the placeholder must not take the row down — with
    `str.format` it raised KeyError inside a signal handler, which is
    LWSM-1082's crash class arriving by a new route.
    """
    from PySide6.QtCore import QCoreApplication, QTranslator

    class Broken(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            return "{port} %2 porta"  # every placeholder wrong

    translator = Broken()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
        assert rows_of(window)[0]._port.text() == "{port} %2 porta"
    finally:
        app.removeTranslator(translator)


# --- LWSM-1113: the palette is applied, not merely built ----------------------


def test_the_window_carries_the_theme_palette(qtbot, built) -> None:
    """`to_palette()` has to reach a widget, and nothing checked that it did.

    `tests/test_theme.py::test_every_palette_role_carries_its_token` asserts the
    returned `QPalette` **object** — so deleting
    `self.setPalette(theme.to_palette())` from `MainWindow.__init__` left all
    150 tests green, twice over (LWSM-1113). The palette was built correctly and
    thrown away, and the only test that could have noticed was looking at the
    wrong end of the call.

    Scope is the window's own palette. It used to carry a note here saying the
    theme "does not in fact reach the window's descendants" — true when it was
    written and **false since LWSM-1118**, which is why it is rewritten rather
    than left standing: a comment stating a fixed defect as current fact is the
    LWSM-1108 class of error, and this project has already had to clear one
    round of those.

    The window now inherits the palette from the application rather than having
    it set directly, so this and
    `test_the_theme_reaches_the_cells_not_only_the_window` redden on the same
    mutation. They are still separate: this one fails if the theme reaches
    nothing at all, that one fails if it reaches the frame and stops there —
    which is exactly the state that survived three reviews.
    """
    from PySide6.QtGui import QColor, QPalette

    theme = Theme.default()
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))

    actual = window.palette().color(QPalette.ColorRole.WindowText)
    assert actual == QColor(theme.text), (
        f"the window's WindowText is {actual.name()}, not the theme's "
        f"{theme.text} — to_palette() was built and never applied"
    )


# --- LWSM-1131 § 4.4: the Rescan seam ----------------------------------------


def rescan_window(
    qtbot,
    built,
    records,
    tmp_path: Path,
    scan_result,
    load=None,
    saves: list | None = None,
) -> tuple[MainWindow, ProjectController]:
    """A window with a Rescan context whose scan and writer are both fakes.

    `testing.md § T1`: nothing here walks a real tree or reaches the real
    config. The scan is a value, not a directory.
    """
    controller = build_controller(built, list(records), FakeProbe())

    def fake_save(path, merged, *, load) -> None:
        if saves is not None:
            saves.append((path, list(merged), load))

    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=lambda _roots: scan_result,
        now=lambda: "2026-08-14T09:00:00Z",
        save=fake_save,
    )
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        rescan=context,
        load=load if load is not None else RegistryMissing("first run"),
    )
    qtbot.addWidget(window)
    return window, controller


def run_rescan(qtbot, window: MainWindow) -> None:
    """Click Rescan and wait for the worker, never sleeping for a duration."""
    window._rescan_button.click()
    qtbot.waitUntil(lambda: not window._rescan_in_flight, timeout=5000)


def test_a_window_with_nothing_to_rescan_has_no_rescan_button(qtbot, built) -> None:
    """No context, no button. An enabled control that cannot work is worse than
    an absent one, and every pre-LWSM-1131 window is built this way."""
    window, _ = window_for(qtbot, built, [record("a", 3000)], FakeProbe())
    assert window._rescan_button is None
    window.shutdown()


def test_a_rescan_adds_a_new_project_and_says_so(qtbot, built, tmp_path) -> None:
    project = tmp_path / "roots" / "web"
    scan = FakeScanResult(
        projects=(FakeDetected(project, "web", port=FakePortFinding(3000)),)
    )
    saves: list = []
    window, controller = rescan_window(qtbot, built, [], tmp_path, scan, saves=saves)

    run_rescan(qtbot, window)

    assert [row.name for row in controller.rows()] == ["web"]
    assert "1 new" in window.statusBar().currentMessage()
    assert saves, "first run must write, or projects.json never comes into existence"
    window.shutdown()


def test_a_rescan_that_changes_nothing_says_so_and_does_not_write(
    qtbot, built, tmp_path
) -> None:
    """§ 4.4's single write trigger: record CONTENT differing from the load.

    A no-op rewrite churns the file's mtime and widens the only window in which
    a concurrent writer can lose an edit, for no gain.
    """
    project = tmp_path / "roots" / "web"
    stored = ProjectRecord(
        path=project,
        name="web",
        port=3000,
        kind=LauncherKind.SHELL,
        argv=("./start.sh",),
        added="2026-08-01T00:00:00Z",
    )
    scan = FakeScanResult(
        projects=(FakeDetected(project, "web", port=FakePortFinding(3000)),)
    )
    saves: list = []
    window, _ = rescan_window(
        qtbot,
        built,
        [stored],
        tmp_path,
        scan,
        load=LoadResult(records=[stored], reasons=[], rows_refused=0),
        saves=saves,
    )

    run_rescan(qtbot, window)

    assert window.statusBar().currentMessage() == "Rescan: no changes"
    assert saves == [], "an all-unchanged merge must not rewrite the file"
    window.shutdown()


def test_a_flag_only_outcome_does_not_write(qtbot, built, tmp_path) -> None:
    """*missing* changes the report and not one field, so it must not write."""
    stored = ProjectRecord(path=tmp_path / "roots" / "gone", name="gone")
    saves: list = []
    window, _ = rescan_window(
        qtbot,
        built,
        [stored],
        tmp_path,
        FakeScanResult(),
        load=LoadResult(records=[stored], reasons=[], rows_refused=0),
        saves=saves,
    )

    run_rescan(qtbot, window)

    assert "1 missing" in window.statusBar().currentMessage()
    assert saves == []
    window.shutdown()


def test_a_read_only_session_reports_rather_than_writing(
    qtbot, built, tmp_path
) -> None:
    """The gate is LWSM-1007's and the SLOT owns it — nothing re-implements it.

    A load that refused a row still merges and still reports; the writer
    refuses, and the user is told the rescan was not saved.
    """
    project = tmp_path / "roots" / "web"

    def refusing_save(path, merged, *, load) -> None:
        raise RegistryError("2 row(s) were refused at load")

    controller = build_controller(built, [], FakeProbe())
    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=lambda _roots: FakeScanResult(projects=(FakeDetected(project, "web"),)),
        now=lambda: "2026-08-14T09:00:00Z",
        save=refusing_save,
    )
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        rescan=context,
        load=LoadResult(records=[], reasons=["bad row"], rows_refused=2),
    )
    qtbot.addWidget(window)

    run_rescan(qtbot, window)

    message = window.statusBar().currentMessage()
    assert "not saved" in message
    assert "refused at load" in message
    assert [row.name for row in controller.rows()] == ["web"], (
        "the merge still runs and is still shown; only the write is refused"
    )
    window.shutdown()


def test_a_rescan_that_raises_re_enables_the_button(qtbot, built, tmp_path) -> None:
    """PySide6 swallows an exception escaping `QRunnable.run()` and emits no
    signal, so without the catch-all the in-flight flag stays set and Rescan
    never comes back."""
    controller = build_controller(built, [], FakeProbe())

    def exploding_scan(_roots):
        raise RuntimeError("the scanner fell over")

    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=exploding_scan,
        now=lambda: "2026-08-14T09:00:00Z",
        save=lambda *a, **k: None,
    )
    window = MainWindow(controller, Theme.default(), [], rescan=context)
    qtbot.addWidget(window)

    run_rescan(qtbot, window)

    assert window._rescan_button.isEnabled()
    assert "Rescan failed" in window.statusBar().currentMessage()
    window.shutdown()


def test_the_summary_omits_zero_counts_and_never_renders_unchanged() -> None:
    """`unchanged` is counted because `counts` is the merge's own tally, and is
    the one outcome that is not news."""
    from lwsm import registry as reg

    assert mainwindow.summarise_merge(dict.fromkeys(reg.OUTCOMES, 0)) == (
        "Rescan: no changes"
    )
    assert mainwindow.summarise_merge({reg.UNCHANGED: 7}) == "Rescan: no changes"
    assert mainwindow.summarise_merge({reg.NEW: 2, reg.CHANGED: 1, reg.MISSING: 1}) == (
        "Rescan: 2 new, 1 changed, 1 missing"
    )


def test_the_summary_order_is_fixed_and_not_dict_order() -> None:
    """§ 4.4 pins the order, so a counts dict built in any order renders the
    same line — which a `for outcome, count in counts.items()` loop would not."""
    from lwsm import registry as reg

    backwards = {reg.MISSING: 1, reg.CHANGED: 1, reg.NEW: 1}
    assert (
        mainwindow.summarise_merge(backwards) == "Rescan: 1 new, 1 changed, 1 missing"
    )
