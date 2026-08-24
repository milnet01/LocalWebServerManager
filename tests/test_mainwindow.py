"""LWSM-1005 INV-6, INV-7, INV-13, INV-15 — the row tells the truth, accessibly.

Headless under QT_QPA_PLATFORM=offscreen (`docs/standards/testing.md § T6`),
which conftest.py sets when it is unset.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import re
import socket
import threading
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import QApplication

from lwsm import __version__, mainwindow, placement, registry, scanner
from lwsm.__main__ import build_window
from lwsm.browsers import Browser
from lwsm.controller import (
    ProjectController,
    ProjectStatus,
    wait_for_abandoned_probes,
)
from lwsm.mainwindow import MIN_TARGET_PX, STATE_GLYPHS, MainWindow, ProjectRow
from lwsm.placement import Rect
from lwsm.ports import PortProbe, PortSnapshot
from lwsm.registry import (
    LauncherKind,
    LoadResult,
    ProjectRecord,
    RegistryError,
    RegistryMissing,
)
from lwsm.settings import SettingsError
from lwsm.theme import DEFAULT_THEME, THEMES, Theme

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
    # test design-accessibility.md § Accessibility makes the blunt version of.
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

    `design-accessibility.md § Accessibility` requires three redundant
    signals — word, colour and glyph — and every assertion above this one
    would pass just as happily if the glyph had simply been deleted. So this
    looks at the pixels.
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


def test_the_row_exposes_its_cells_and_its_buttons(qtbot, built) -> None:
    """The count is the assertion that would have caught this: the row exposed
    four children, and setAccessibleName("") did not remove the fourth —
    QAccessibleDisplay falls back to QLabel::text() when the name is empty.

    The buttons joined the list with LWSM-1010 and LWSM-1016, and are asserted
    **by exact name**, not merely counted. Each carries the project's name,
    because three rows of a bare "Start" leave a screen-reader user with three
    identical controls and no way to tell which is which (`§ O8`). The
    decorative glyph is still absent, which is what this test was written for.
    """
    window, _ = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    names = accessible_children(rows_of(window)[0])

    assert names == [
        "running",
        "a",
        "port 5005",
        # LWSM-1187's browser picker. A control, so it carries its own name
        # rather than joining the row's announcement -- and it is present on
        # every row whether or not any browser is installed, because the
        # "Default browser" entry always exists.
        "Default browser",
        "Start a",
        "Stop a",
        "Restart a",
        "Open a in a browser",
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
    """`design-accessibility.md § Accessibility` promises "a state change
    announces itself once". Qt does not notify AT-SPI when an accessible name
    changes, so setAccessibleName alone left that promise unimplemented."""
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
# which design-accessibility.md § Accessibility names as an anti-pattern outright.
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
    and colour is one of `design-accessibility.md § Accessibility`'s three
    redundant signals.

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


def test_the_title_bar_carries_the_version(qtbot, built) -> None:
    """LWSM-1186: the title names the running version.

    Asserted against `__version__` rather than against a literal. The first
    release bumps that constant, and a test pinned to `0.0.0` would redden CI
    on the release commit rather than on a defect.

    This test deliberately does NOT send `LanguageChange` and assert the title
    again. It was drafted that way, and the mutation run showed that assertion
    was vacuous: with no translator installed a retranslate rebuilds the same
    string, so it held whether or not `changeEvent` touched the title at all —
    deleting that `setWindowTitle` left it green. What pins the version across
    a retranslate is `test_a_translator_installed_later_reaches_an_existing_row`,
    whose uppercasing translator makes the two titles differ; that mutant dies
    there.
    """
    window, _ = window_for(qtbot, built, [record("a", None)], FakeProbe())
    assert window.windowTitle() == f"Local Web Server Manager {__version__}"


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
        assert window.windowTitle() == f"LOCAL WEB SERVER MANAGER {__version__}"

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
        assert window.windowTitle() == f"LOCAL WEB SERVER MANAGER {__version__}"
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
    browsers_available: tuple = (),
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
        # Injected, never scanned: conftest points XDG_DATA_DIRS at an empty
        # directory so the real scan finds nothing, and a test that wants
        # browsers says which (`§ T1`).
        list_browsers=lambda: browsers_available,
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


def test_a_successful_write_stops_the_next_identical_rescan(
    qtbot, built, tmp_path
) -> None:
    """The refresh after a successful save, which nothing measured.

    A first run has no file, so the gate writes unconditionally — and stays
    that way for the session unless the save teaches it what is now on disk.
    Without the refresh every later rescan rewrites an unchanged file, churning
    its mtime and widening the only window in which a concurrent writer can
    lose an edit. Found by mutating the refresh out while shipping LWSM-1185;
    every test stayed green.
    """
    project = tmp_path / "roots" / "web"
    scan = FakeScanResult(projects=(FakeDetected(project, "web"),))
    saves: list = []
    window, _ = rescan_window(qtbot, built, [], tmp_path, scan, saves=saves)

    run_rescan(qtbot, window)
    assert len(saves) == 1, "first run must create the file"

    run_rescan(qtbot, window)
    assert len(saves) == 1, (
        "nothing changed, and the save told the gate what is on disk"
    )
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


def test_a_refused_write_is_retried_by_the_next_rescan(qtbot, built, tmp_path) -> None:
    """LWSM-1166: the gate compares against the LOAD, never the in-memory set.

    `_apply_merge` calls `set_records` unconditionally, so after a refused write
    the in-memory set already holds the merge. A gate reading that set finds no
    difference on the next rescan, writes nothing, and reports "no changes" —
    the app looks healthy while nothing has ever been persisted. Any transient
    failure (read-only mount, ENOSPC) has the same shape, so the retry the user
    makes is silently a no-op.

    The two rescans are asserted against each other in one test: a gate that
    never writes passes the second half alone, and a gate that always writes
    passes the first half alone.
    """
    project = tmp_path / "roots" / "web"
    attempts: list = []

    def refusing_save(path, merged, *, load) -> None:
        attempts.append(list(merged))
        raise RegistryError("read-only file system")

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
        load=LoadResult(records=[], reasons=[], rows_refused=0),
    )
    qtbot.addWidget(window)

    run_rescan(qtbot, window)
    assert len(attempts) == 1
    assert "not saved" in window.statusBar().currentMessage()

    run_rescan(qtbot, window)
    assert len(attempts) == 2, (
        "the second rescan must try again: nothing has reached the disk yet"
    )
    assert "not saved" in window.statusBar().currentMessage(), (
        "and must still say so, rather than reporting no changes"
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


def test_a_writer_that_escapes_the_slot_still_re_enables_the_button(
    qtbot, built, tmp_path
) -> None:
    """`_finish_rescan` is the only place `setEnabled(True)` happens, and it sat
    after the try block rather than in a `finally` (LWSM-1135).

    So anything the slot does not catch disabled Rescan for the rest of the
    session — which is exactly what a raw `OSError` out of `save_projects` did,
    with PySide6 swallowing the traceback so nothing said why. The guard is on
    the mechanism, not on that one exception: this raises something
    `_on_rescan_done` has never claimed to handle.
    """
    controller = build_controller(built, [], FakeProbe())

    def escaping_save(path, merged, *, load) -> None:
        raise OSError("the disk went away")

    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=lambda _roots: FakeScanResult(
            projects=(FakeDetected(tmp_path / "roots" / "web", "web"),)
        ),
        now=lambda: "2026-08-14T09:00:00Z",
        save=escaping_save,
    )
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        rescan=context,
        load=RegistryMissing("first run"),
    )
    qtbot.addWidget(window)

    run_rescan(qtbot, window)

    assert window._rescan_button.isEnabled(), (
        "Rescan must come back however the slot ended"
    )
    assert not window._rescan_in_flight
    assert "Rescan failed" in window.statusBar().currentMessage(), (
        "Qt swallows what escapes this slot, so it is reported here or nowhere"
    )
    assert "the disk went away" in window.statusBar().currentMessage()
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


# --- LWSM-1185: hiding a project ---------------------------------------------


def hide_window(qtbot, built, tmp_path, records, saves):
    """A window with a writer, so the hide toggle has somewhere to persist to."""
    return rescan_window(
        qtbot, built, records, tmp_path, FakeScanResult(projects=()), saves=saves
    )


def row_named(window, name: str) -> ProjectRow:
    return next(row for row in window._ordered_rows() if name in row._name.text())


def test_a_hidden_project_is_not_listed(qtbot, built, tmp_path) -> None:
    """`ProjectRecord.hidden` has been parsed, validated and persisted since
    LWSM-1007 and read by nothing. A stored flag no consumer honours looks
    exactly like a working feature from the file's side."""
    saves: list = []
    window, _ = hide_window(
        qtbot,
        built,
        tmp_path,
        [record("keep", 3000), dataclasses.replace(record("gone", 3001), hidden=True)],
        saves,
    )

    shown = [row._name.text() for row in window._visible_rows()]
    assert "keep" in " ".join(shown)
    assert "gone" not in " ".join(shown)
    window.shutdown()


def test_the_view_menu_shows_hidden_projects_again(qtbot, built, tmp_path) -> None:
    """Nothing may become unrecoverable without hand-editing the file (user
    decision, 2026-08-24). The toggle is what makes hiding reversible, and the
    marker is what says WHICH rows are back — as text, because colour alone
    carries no meaning to a screen reader."""
    saves: list = []
    window, _ = hide_window(
        qtbot,
        built,
        tmp_path,
        [dataclasses.replace(record("gone", 3001), hidden=True)],
        saves,
    )
    assert window._visible_rows() == []

    window._show_hidden_action.trigger()

    shown = window._visible_rows()
    assert len(shown) == 1
    assert "hidden" in shown[0]._name.text().casefold(), (
        "a row that is back must say why it is back"
    )
    assert "hidden" in shown[0].accessibleName().casefold(), (
        "and must say it to a screen reader, from the same rendered string"
    )

    window._show_hidden_action.trigger()
    assert window._visible_rows() == []
    window.shutdown()


def test_hiding_a_project_from_its_menu_persists_it(qtbot, built, tmp_path) -> None:
    """Driven through the ACTION, never the method it calls.

    A method whose whole value is being wired to something looks identical to a
    working one when its own unit test invokes it directly — the trap
    `CLAUDE.md` records against `rotate_if_needed`.
    """
    saves: list = []
    window, controller = hide_window(
        qtbot, built, tmp_path, [record("gone", 3001)], saves
    )
    row = row_named(window, "gone")

    # Through the CONTEXT MENU Qt will actually render, which under
    # `ActionsContextMenu` is exactly the widget's own action list. Reaching
    # for `row.hide_action` instead would test the method and not the wiring.
    assert row.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu
    (action,) = row.actions()
    assert "hide" in action.text().casefold()
    action.trigger()

    assert [r.hidden for r in controller.records()] == [True]
    assert saves, "the choice must outlive the session"
    assert [r.hidden for r in saves[-1][1]] == [True]
    assert window._visible_rows() == [], "and the row goes away at once"
    window.shutdown()


def test_unhiding_a_project_puts_it_back(qtbot, built, tmp_path) -> None:
    saves: list = []
    window, controller = hide_window(
        qtbot,
        built,
        tmp_path,
        [dataclasses.replace(record("gone", 3001), hidden=True)],
        saves,
    )
    window._show_hidden_action.trigger()
    row = row_named(window, "gone")

    (action,) = row.actions()
    assert "show" in action.text().casefold(), (
        "an already-hidden row must offer the way back, not the way in"
    )
    action.trigger()

    assert [r.hidden for r in controller.records()] == [False]
    assert [r.hidden for r in saves[-1][1]] == [False]
    window.shutdown()


def test_hidden_survives_a_rescan(qtbot, built, tmp_path) -> None:
    """`hidden` is a USER field, so a rescan refreshes the detected half around
    it. Asserted rather than assumed — LWSM-1007 INV-1 is what keeps the two
    halves complete, and a field dropped from `USER_FIELDS` would be silent."""
    assert "hidden" in registry.USER_FIELDS


# --- LWSM-1016: open in browser ----------------------------------------------


class ManagingSupervisor:
    """A supervisor that reports a chosen set of projects as ones IT spawned.

    `running()` is the whole surface `RowView.managed` reads, and since
    LWSM-1141 that is the difference between a server this manager can vouch for
    and one it merely observed on the socket table. A fake that always claimed
    everything could not express the hazard at all.
    """

    def __init__(self, managed=()) -> None:
        self._running = {Path(path): object() for path in managed}

    def running(self) -> dict:
        return dict(self._running)

    def exited(self, project: Path) -> bool:
        return False


def opening_window(
    qtbot, built, records, probe, opened: list, managed=None
) -> MainWindow:
    """A window whose `openUrl` is a spy — a test must never launch a browser.

    Every record counts as managed unless the caller says otherwise: these tests
    are about the URL and the click, and a window supervising nothing would
    disable Open on every row and make all of them pass for the wrong reason.
    """
    owned = [row.path for row in records] if managed is None else managed
    controller = ProjectController(records, probe, ManagingSupervisor(owned))
    built.append(controller)
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        open_url=lambda url: opened.append(url) or True,
    )
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    return window


def test_open_is_offered_only_while_a_port_is_observed_bound(qtbot, built) -> None:
    """Not while `starting`: there is no bound port yet, so the browser would
    open on nothing and the user would blame the app rather than the wait."""
    opened: list = []
    window = opening_window(qtbot, built, [record("a", 5005)], FakeProbe(5005), opened)
    assert rows_of(window)[0].open_button.isEnabled()

    stopped = opening_window(qtbot, built, [record("b", 6006)], FakeProbe(), opened)
    assert not rows_of(stopped)[0].open_button.isEnabled()


def test_open_uses_the_port_that_is_bound(qtbot, built) -> None:
    """`http://localhost:<bound port>`, built through QUrl rather than
    concatenated — the requested and the bound port differ exactly when a
    project ignored `PORT`."""
    opened: list = []
    window = opening_window(qtbot, built, [record("a", 5005)], FakeProbe(5005), opened)

    rows_of(window)[0].open_button.click()

    assert len(opened) == 1
    assert opened[0].toString() == "http://localhost:5005/"
    assert opened[0].port() == 5005
    assert opened[0].host() == "localhost"


def test_open_reads_the_port_at_click_time_not_at_build_time(qtbot, built) -> None:
    """An override or a rescan can move the port. Opening a value cached when
    the button was created is the confidently-wrong failure ADR-0003 records a
    sibling project having shipped — it kept POSTing to the old port while the
    server was perfectly healthy somewhere else."""
    opened: list = []
    # Managed, so Open is offered at all (LWSM-1141) — this test is about which
    # port the button reads, and a disabled button would pass it vacuously.
    controller = ProjectController(
        [record("a", 5005)],
        FakeProbe(5005, 7007),
        ManagingSupervisor([Path("/srv/a")]),
    )
    built.append(controller)
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        open_url=lambda url: opened.append(url) or True,
    )
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    # `set_records` emits on its own, and no second poll is waited for on
    # purpose: both 5005 and 7007 are bound in this fixture, so the derived
    # status does not change and `_maybe_emit` correctly stays quiet. Waiting
    # for a signal that must not come is how this test first failed.
    controller.set_records([record("a", 7007)])
    rows_of(window)[0].open_button.click()

    assert opened[0].port() == 7007, "the button opened a port that had moved"


def test_a_browser_that_will_not_open_is_reported(qtbot, built) -> None:
    """`openUrl` returns False when the desktop has no handler. Silence here
    looks identical to a browser that opened behind the window."""
    controller = ProjectController(
        [record("a", 5005)], FakeProbe(5005), ManagingSupervisor([Path("/srv/a")])
    )
    built.append(controller)
    window = MainWindow(controller, Theme.default(), [], open_url=lambda _url: False)
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()

    rows_of(window)[0].open_button.click()

    assert "Could not open a browser" in window.statusBar().currentMessage()


def test_the_url_is_built_not_concatenated() -> None:
    """A port substituted into a string before parsing is how
    `http://localhost:0@evil.example/` gets made. `QUrl` refuses to produce one
    from an integer port, which is the whole reason for the shape."""
    url = mainwindow.project_url(8080)
    assert url.scheme() == "http"
    assert url.host() == "localhost"
    assert url.userInfo() == ""
    assert url.toString() == "http://localhost:8080/"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        # start, stop, restart, open
        (ProjectStatus.STOPPED, (True, False, False, False)),
        (ProjectStatus.RUNNING, (False, True, True, True)),
        (ProjectStatus.UNKNOWN, (True, False, False, False)),
        (ProjectStatus.STARTING, (False, False, False, False)),
        (ProjectStatus.STOPPING, (False, False, False, False)),
    ],
)
def test_which_buttons_each_state_offers(qtbot, status, expected) -> None:
    """Every state against every button, because the interesting ones are the
    two overlay states and no other test reaches them.

    Both overlay states disable all four: a second Stop while one is in flight
    would signal a group whose leader may already be reaped, a Start during a
    stop is the race the pre-flight check exists to refuse, and Open while
    `starting` would launch a browser at a port nothing has bound yet.
    """
    from lwsm.controller import RowView
    from lwsm.mainwindow import ProjectRow

    row = ProjectRow(
        RowView(
            path=Path("/srv/a"),
            name="a",
            effective_port=5005,
            status=status,
            # This test varies the STATE. Ownership is the other axis Open
            # depends on since LWSM-1141 and has its own test below; pinned true
            # here so a failure names the state that broke rather than both.
            managed=True,
        ),
        Theme.default(),
    )
    qtbot.addWidget(row)

    assert (
        row.start_button.isEnabled(),
        row.stop_button.isEnabled(),
        row.restart_button.isEnabled(),
        row.open_button.isEnabled(),
    ) == expected


def test_each_rows_buttons_drive_that_row(qtbot, built) -> None:
    """The bug a one-row fixture cannot see.

    A lambda closing over the loop variable leaves every row's buttons driving
    the LAST project in the list — which looks completely correct until there
    are two rows, and then silently opens, starts and stops the wrong project.
    """
    opened: list = []
    window = opening_window(
        qtbot,
        built,
        [record("a", 5005), record("b", 6006)],
        FakeProbe(5005, 6006),
        opened,
    )

    rows_of(window)[0].open_button.click()

    assert opened[0].port() == 5005, "the first row opened another row's port"


# --- LWSM-1145: the rows line up, because the columns are shared --------------


def aligned_window(qtbot, built, records, probe):
    """A shown window whose rows have deliberately different cell widths.

    A one-row fixture cannot see a per-row bug — `CLAUDE.md` records that trap
    twice over, and column alignment is undefined below two rows anyway.
    """
    window, controller = window_for(qtbot, built, records, probe)
    with qtbot.waitExposed(window):
        window.show()
    return window, controller


UNEVEN = [
    record("a", 80),
    record("a-considerably-longer-project-name", 5005),
    record("mid", 65535),
]


def start_button_xs(window: MainWindow) -> list[int]:
    return [row.start_button.mapTo(window, QPoint(0, 0)).x() for row in rows_of(window)]


def test_every_start_button_lands_at_the_same_x(qtbot, built) -> None:
    """LWSM-1145's acceptance criterion, stated as the user saw it.

    Each `ProjectRow` is its own `QHBoxLayout` and Qt syncs nothing between
    sibling layouts, so before the shared geometry the buttons stepped in and
    out by the width of each project's name.
    """
    window, _ = aligned_window(qtbot, built, UNEVEN, FakeProbe(5005))

    xs = start_button_xs(window)
    assert len(xs) == len(UNEVEN), "the fixture must have more than one row"
    assert len(set(xs)) == 1, f"Start buttons at differing x: {xs}"


def test_the_columns_stay_aligned_after_an_in_place_update(qtbot, built) -> None:
    """Rows are created once and updated in place (LWSM-1131), so the shared
    widths have to be re-derived after an update rather than settled at
    construction — a rescan can rename a project without replacing its row."""
    window, controller = aligned_window(qtbot, built, UNEVEN, FakeProbe(5005))
    row = next(r for p, r in window._rows.items() if p == Path("/srv/mid"))
    # The RENDERED name, not the column width. Width was the precondition until
    # LWSM-1174 capped the name column: the fixture's widest name already sits
    # at the cap, so a rename can no longer widen it and the precondition would
    # fail for a reason that says nothing about alignment. What it was really
    # proving is that the in-place update landed, which the text says directly.
    was = row._name.text()

    renamed = [
        r
        if r.path != Path("/srv/mid")
        else dataclasses.replace(r, name="mid-renamed-to-something-far-longer")
        for r in controller.records()
    ]
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.set_records(renamed)
    qtbot.waitUntil(lambda: row._name.text() != was, timeout=2000)

    assert row is next(r for p, r in window._rows.items() if p == Path("/srv/mid")), (
        "the row must have been updated in place, not rebuilt"
    )
    xs = start_button_xs(window)
    assert len(set(xs)) == 1, f"Start buttons at differing x after update: {xs}"


def test_a_column_shrinks_when_the_widest_project_leaves(qtbot, built) -> None:
    """The guard against a monotonic column.

    `apply_column_widths` sets a fixed width, so a natural width read back off
    `minimumWidth()` could only ever grow — the long name would keep its column
    reserved after the project it belonged to was gone.
    """
    window, controller = aligned_window(qtbot, built, UNEVEN, FakeProbe(5005))
    wide = rows_of(window)[0]._name.width()

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.set_records([record("a", 80), record("mid", 65535)])
    qtbot.waitUntil(lambda: rows_of(window)[0]._name.width() < wide, timeout=2000)

    assert len(set(start_button_xs(window))) == 1


# --- LWSM-1149: the window opens big enough to read ---------------------------


def many(count: int) -> list:
    return [record(f"project-{i:02d}", 3000 + i) for i in range(count)]


def sized_window(qtbot, built, records):
    window, controller = window_for(qtbot, built, records, FakeProbe())
    with qtbot.waitExposed(window):
        window.show()
    return window, controller


def row_pitch(window: MainWindow) -> int:
    """One row plus the gap under it — the unit the opening height is built in."""
    return rows_of(window)[0].sizeHint().height() + window._rows_layout.spacing()


def test_a_short_list_opens_with_every_row_visible(qtbot, built) -> None:
    """The first impression a new user gets. Qt's own default was ~790x520 with
    the list crushed against the chrome, and there is nothing remembered on a
    first run — restoring a chosen geometry is LWSM-1033's."""
    window, _ = sized_window(qtbot, built, many(5))

    bar = window._scroll.verticalScrollBar()
    assert bar.maximum() == 0, (
        f"5 rows should need no scrolling, but the list overflows by "
        f"{bar.maximum()} px at {window.width()}x{window.height()}"
    )


def test_the_opening_height_tracks_the_list_up_to_a_cap(qtbot, built) -> None:
    """Both halves in one test, because either alone is vacuous.

    A window that ignores its content passes 'a long list does not grow the
    window' by never growing at all — which is how the first version of this
    test survived deleting the whole mechanism. Pinning the short case against
    the long one is what makes the pair mean something.
    """
    cap = mainwindow.DEFAULT_VISIBLE_ROWS
    short = sized_window(qtbot, built, many(3))[0]
    full = sized_window(qtbot, built, many(cap))[0]
    over = sized_window(qtbot, built, many(cap + 40))[0]

    assert short.height() < full.height(), (
        f"the opening height must follow the list below the cap: "
        f"3 rows gave {short.height()}, {cap} gave {full.height()}"
    )
    assert full.height() == over.height(), (
        f"the window must stop growing at {cap} rows, not track the list: "
        f"{full.height()} vs {over.height()}"
    )
    assert over._scroll.verticalScrollBar().maximum() > 0, "the rest must scroll"


def test_the_minimum_height_still_shows_three_rows(qtbot, built) -> None:
    """`a sensible minimum below which the columns would collide`.

    The *width* floor is not asserted here and that is deliberate: the columns
    are fixed-width, so Qt's own layout minimum already forbids a window narrow
    enough to clip one, and an assertion about it could not fail. The height is
    the half this code actually decides — a scroll area's minimum is nothing at
    all, so without a floor the window shrinks to a single sliver of list.
    """
    window, _ = sized_window(qtbot, built, many(20))
    pitch = row_pitch(window)

    window.resize(window.minimumSize())
    qtbot.waitUntil(lambda: window.height() == window.minimumHeight(), timeout=2000)

    visible = window._scroll.viewport().height() // pitch
    assert visible >= mainwindow.MIN_VISIBLE_ROWS, (
        f"at its minimum height the window shows {visible} rows, fewer than "
        f"the {mainwindow.MIN_VISIBLE_ROWS} it must stay legible at"
    )


def test_the_opening_size_is_not_reapplied_over_a_user_resize(qtbot, built) -> None:
    """Applied once. It runs from `_sync_rows` because a first run has no
    records and the rows arrive with the first scan — but a second application
    would fight a window the user had already sized by hand."""
    window, controller = sized_window(qtbot, built, many(4))
    window.resize(window.width() + 200, window.height() + 150)
    qtbot.waitUntil(lambda: window.height() > window.minimumHeight(), timeout=2000)
    chosen = window.size()

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.set_records(many(6))
    qtbot.wait(50)

    assert window.size() == chosen, (
        f"the window was resized out from under the user: {window.size()} was {chosen}"
    )


def test_the_geometry_waits_for_the_rows_a_first_run_has_not_scanned_yet(
    qtbot, built, tmp_path
) -> None:
    """A first run opens with an empty registry, so there is no row to measure
    until the scan lands."""
    window, _ = rescan_window(
        qtbot,
        built,
        [],
        tmp_path,
        FakeScanResult(
            projects=(
                FakeDetected(
                    path=tmp_path / "found", name="found", port=FakePortFinding(5005)
                ),
            )
        ),
    )
    with qtbot.waitExposed(window):
        window.show()
    assert not window._geometry_applied, "nothing to measure with no rows"

    run_rescan(qtbot, window)

    assert window._geometry_applied, "the first rows must set the opening size"
    assert window.minimumHeight() > 0


def test_rescan_is_a_control_not_a_full_width_strip(qtbot, built, tmp_path) -> None:
    """A button stretched across the window reads as its primary purpose, and
    rescanning is not what the user came here to do."""
    window, _ = rescan_window(qtbot, built, many(3), tmp_path, FakeScanResult())
    with qtbot.waitExposed(window):
        window.show()

    button = window._rescan_button
    assert button.width() < window.width() // 2, (
        f"Rescan is {button.width()} px wide in a {window.width()} px window"
    )
    left = button.mapTo(window, QPoint(0, 0)).x()
    assert left > window.width() // 2, "Rescan should sit at the right of its strip"


# --- LWSM-1146: the menu bar -------------------------------------------------


def menu_titles(window: MainWindow) -> list[str]:
    """Top-level menu labels, in bar order."""
    return [action.text() for action in window.menuBar().actions()]


def entry_texts(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def two_rows() -> list[ProjectRecord]:
    """Two, never one. A one-row fixture has hidden a per-row bug in this file
    twice, and a bar that is a window-level singleton is exactly the shape that
    reads as fine against a single row."""
    return [record("a", 5005), record("b", None)]


def test_the_bar_offers_settings_and_carries_its_own_mnemonics(qtbot, built) -> None:
    """LWSM-1146 owns the BAR, not the dialog.

    The `&` is asserted because it is the whole of the item's "must not
    foreclose LWSM-1040" clause: a bar built without mnemonics is unreachable
    from the keyboard until someone adds them, which is `§ O8` clause 2
    retrofitted, and § O8 exists to stop exactly that.
    """
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))

    # LWSM-1033's View menu sits between them. A third top-level menu for one
    # action was the decision this whole-list assertion demands: "Centre on
    # screen" is a verb, and every entry in Settings is a choice that then
    # stays chosen.
    assert menu_titles(window) == ["&File", "&View", "&Settings"]
    # LWSM-1031 added the Theme submenu ABOVE Preferences, because it is the
    # entry that works today; LWSM-1032's Text size joined it for the same
    # reason. Asserted as the whole list rather than as membership, so an entry
    # added without a decision about its placement lands here as a failure.
    assert entry_texts(window._settings_menu) == [
        "&Theme",
        "Te&xt size",
        "&Preferences...",
    ]
    assert all("&" in title for title in menu_titles(window))
    assert "&" in window._theme_menu.title()


def test_preferences_opens_the_injected_dialog(qtbot, built) -> None:
    """The seam LWSM-1018 attaches through, and the reason this item could land
    without it — the same injection shape as `confirm` and `open_url`."""
    opened: list[str] = []
    controller = build_controller(built, two_rows(), FakeProbe(5005))
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        open_settings=lambda: opened.append("dialog"),
    )
    qtbot.addWidget(window)

    window._settings_action.trigger()

    assert opened == ["dialog"]


def test_preferences_with_no_dialog_says_so_rather_than_doing_nothing(
    qtbot, built
) -> None:
    """A menu entry that does nothing when chosen is indistinguishable from a
    broken one, which is why the default is a message and not a silent pass or
    a greyed entry."""
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))

    window._settings_action.trigger()

    assert window.statusBar().currentMessage() == "Settings are not available yet."


def test_a_window_with_nothing_to_rescan_has_no_rescan_entry(qtbot, built) -> None:
    """The same rule the button follows: no context, no control. Asserted on
    the File menu's contents as well as on the attribute, because an entry that
    exists but is never reached would satisfy the attribute alone."""
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe())

    assert window._rescan_action is None
    assert entry_texts(window._file_menu) == ["&Quit"]
    window.shutdown()


def test_rescan_from_the_menu_greys_the_button_with_it(qtbot, built, tmp_path) -> None:
    """One control with two faces.

    Written with the enable/disable in two places, the menu entry stayed live
    while the button greyed — an offer to start a second merge over the first,
    invisible to every test that only ever clicked the button. The assertions
    run before the loop is spun, so the worker's completion signal has not been
    delivered yet.
    """
    project = tmp_path / "roots" / "web"
    scan = FakeScanResult(
        projects=(FakeDetected(project, "web", port=FakePortFinding(3000)),)
    )
    window, controller = rescan_window(qtbot, built, [], tmp_path, scan)

    window._rescan_action.trigger()

    assert window._rescan_in_flight, "the menu entry never reached _start_rescan"
    assert not window._rescan_action.isEnabled()
    assert not window._rescan_button.isEnabled()

    qtbot.waitUntil(lambda: not window._rescan_in_flight, timeout=5000)

    assert window._rescan_action.isEnabled()
    assert window._rescan_button.isEnabled()
    assert [row.name for row in controller.rows()] == ["web"]
    window.shutdown()


def test_the_menu_labels_follow_a_language_change(qtbot, built) -> None:
    """The bar is retranslated from `changeEvent` like the rows are.

    The event is posted by hand, so this does NOT prove Qt delivers a
    `LanguageChange` to this window — see
    `test_a_translator_installed_later_reaches_an_existing_row`, which records
    why that cannot be asserted here. What it does prove is that the labels are
    re-derived rather than fixed at construction.
    """
    from PySide6.QtCore import QCoreApplication, QEvent, QTranslator

    class Shouting(QTranslator):
        def translate(self, context, sourceText, _disambiguation=None, n=-1) -> str:
            return sourceText.upper()

    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    assert window._settings_action.text() == "&Preferences..."

    translator = Shouting()
    app = QCoreApplication.instance()
    assert app.installTranslator(translator)
    try:
        window.changeEvent(QEvent(QEvent.Type.LanguageChange))

        assert window._settings_menu.title() == "&SETTINGS"
        assert window._settings_action.text() == "&PREFERENCES..."
        assert window._file_menu.title() == "&FILE"
    finally:
        app.removeTranslator(translator)


def test_quit_from_the_menu_closes_the_window(qtbot, built) -> None:
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    window.show()
    qtbot.waitUntil(window.isVisible, timeout=2000)

    window._quit_action.trigger()

    assert not window.isVisible()


# --- LWSM-1031: the theme picker, and the switch it drives --------------------


def themed_window(qtbot, built, save=None) -> MainWindow:
    """Two rows, always. A one-row fixture has hidden a per-row bug in this
    file twice, and a theme swap is per-row work: every row caches its own
    `Theme` and its own glyph colour."""
    controller = build_controller(built, two_rows(), FakeProbe(5005))
    window = MainWindow(controller, Theme.default(), [], save_theme=save)
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    return window


def test_the_picker_offers_every_theme_grouped_light_dark_assistive(
    qtbot, built
) -> None:
    """Derived from the registry, so a palette added to `theme.py` appears
    without anyone editing the menu — and asserted in ORDER, because the
    grouping is the whole reason `is_dark` and `high_contrast` are on the
    theme rather than kept in a list beside it."""
    window = themed_window(qtbot, built)

    assert [
        action.text()
        for action in window._theme_menu.actions()
        if not action.isSeparator()
    ] == [
        THEMES[name].label
        for name in (
            "ledger",
            "parchment",
            "mint",
            "midnight",
            "graphite",
            "emerald",
            "highcontrast-light",
            "highcontrast-dark",
        )
    ]
    assert set(window._theme_actions) == set(THEMES)
    # Two separators: light|dark and dark|assistive.
    assert sum(a.isSeparator() for a in window._theme_menu.actions()) == 2


def test_the_checked_entry_is_the_live_theme(qtbot, built) -> None:
    """Exclusive, so choosing one clears the last without anyone clearing it.
    Asserted after a switch as well as at construction: the check has to
    follow `set_theme`, which settings.json restoring a theme also calls with
    no action having been triggered."""
    window = themed_window(qtbot, built)

    checked = [name for name, a in window._theme_actions.items() if a.isChecked()]
    assert checked == [DEFAULT_THEME]

    window.set_theme("emerald")

    checked = [name for name, a in window._theme_actions.items() if a.isChecked()]
    assert checked == ["emerald"]


def test_choosing_a_theme_repaints_every_row_not_just_the_last(qtbot, built) -> None:
    """The closure test, and the reason the fixture has two rows.

    `lambda: self.set_theme(name)` closing over the loop variable makes every
    entry select the LAST theme — the exact bug that shipped on the row
    buttons once already. With one row, or with one menu entry checked, it
    reads as fine. Every entry is triggered and each must select ITSELF.
    """
    window = themed_window(qtbot, built)

    for name, action in window._theme_actions.items():
        action.trigger()
        assert window._theme is THEMES[name], f"{name} selected something else"
        for row in rows_of(window):
            assert row._theme is THEMES[name], f"{name} did not reach every row"


def test_a_swap_moves_the_glyph_colour_and_not_only_the_word(qtbot, built) -> None:
    """LWSM-1111 named this as the live edge the day the palette could change.

    `update_from` short-circuits on an unchanged `RowView` and that guard
    caches `_glyph_color`, so a swap would restyle the state WORD through the
    new style sheet while the painted glyph kept the old palette's colour. The
    `RowView` is deliberately not touched between the two reads — that is the
    condition the guard fires on.
    """
    window = themed_window(qtbot, built)
    window.set_theme("ledger")
    before = [row._glyph_color.name() for row in rows_of(window)]

    window.set_theme("emerald")

    after = [row._glyph_color.name() for row in rows_of(window)]
    assert before != after
    for row, colour in zip(rows_of(window), after, strict=True):
        assert colour == THEMES["emerald"].state_color(row._view.status).name()


def test_the_swap_reaches_the_application_palette_not_only_the_window(
    qtbot, built
) -> None:
    """LWSM-1118: `setStyleSheet` installs QStyleSheetStyle, which re-resolves
    every descendant's palette from the APPLICATION palette — so a
    `self.setPalette` themes the window frame and nothing inside it. The
    switch has to apply it where `__init__` applies it."""
    window = themed_window(qtbot, built)

    window.set_theme("highcontrast-dark")

    app = QApplication.instance()
    assert app is not None
    expected = THEMES["highcontrast-dark"]
    assert app.palette().color(QPalette.ColorRole.Window).name() == expected.window
    assert expected.state_running in window.styleSheet()


def test_the_choice_is_handed_to_the_saver(qtbot, built) -> None:
    """The seam exists so a test cannot write to the developer's own
    ~/.config. `build_window` injects the real one."""
    saved: list[str] = []
    window = themed_window(qtbot, built, save=saved.append)

    window._theme_actions["mint"].trigger()

    assert saved == ["mint"]


def test_a_save_failure_is_reported_and_does_not_undo_the_switch(qtbot, built) -> None:
    """A settings file that cannot be written must not undo a switch the user
    can already see happen — but it must not be silent either, or the choice
    quietly fails to survive the next start."""

    def refuse(_theme_id: str) -> None:
        raise SettingsError("read-only file system")

    window = themed_window(qtbot, built, save=refuse)

    window.set_theme("graphite")

    assert window._theme is THEMES["graphite"]
    for row in rows_of(window):
        assert row._theme is THEMES["graphite"]
    assert "read-only file system" in window.statusBar().currentMessage()


# --- LWSM-1141: Open is offered only for a server this manager started --------


def test_open_is_refused_for_a_server_this_manager_did_not_start(qtbot, built) -> None:
    """ADR-0004's threat model, and it governs (user decision, 2026-08-15).

    `chdir()` is free, so any local process can bind a project's port and be
    classified `running` — indistinguishably from one of ours, because ADR-0004
    derives state from the socket table and not from ownership. Opening a
    browser on it is localhost phishing with this app's credibility behind it.
    The ADR's full mitigation is a disclosure dialog, which needs P06's state
    model; restricting Open to what the supervisor actually spawned is the
    interim the roadmap scopes.

    Two rows, both `running`, differing only in ownership. A one-row fixture
    could not tell "Open is disabled for a foreign server" from "Open is
    disabled" — `CLAUDE.md`'s one-row-fixture trap, applied to a two-member set.
    """
    opened: list = []
    window = opening_window(
        qtbot,
        built,
        [record("ours", 5005), record("theirs", 6006)],
        FakeProbe(5005, 6006),
        opened,
        managed=[Path("/srv/ours")],
    )
    ours, theirs = rows_of(window)

    assert ours.open_button.isEnabled()
    assert not theirs.open_button.isEnabled(), (
        "Open was offered on a port held by a process this manager did not start"
    )
    # The row still reads `running`, and must: this restricts the ACTION, it
    # does not make the app lie about what it observed (ADR-0004).
    assert "running" in theirs.accessibleName()


def test_ownership_alone_is_not_re_announced_to_a_screen_reader(
    qtbot, announcements
) -> None:
    """`managed` renders as button enablement and as no text at all.

    So the RowView equality check that gates the announcement stopped being
    sufficient on its own at LWSM-1141: a project leaving the supervisor's set
    changes the view without changing a word of what a screen reader reads out,
    and an announcement of an unchanged name is the once-a-second
    re-announcement that check exists to prevent — INV-22 arriving by a third
    route.

    Dies on removing the `name_changed` gate in `update_from`.
    """
    from lwsm.controller import RowView
    from lwsm.mainwindow import ProjectRow

    view = RowView(
        path=Path("/srv/a"),
        name="a",
        effective_port=5005,
        status=ProjectStatus.RUNNING,
        managed=True,
    )
    row = ProjectRow(view, Theme.default())
    qtbot.addWidget(row)
    announced_before = row.accessibleName()
    announcements.clear()

    row.update_from(dataclasses.replace(view, managed=False))

    assert not row.open_button.isEnabled(), "the row did not take the new view"
    assert row.accessibleName() == announced_before
    assert announcements == [], (
        "a change no screen reader can hear was announced to one"
    )


# --- LWSM-1139: shutdown is the bounded teardown its caller documents ---------


def blocking_rescan_window(qtbot, built, tmp_path, saves: list, release):
    """A window whose rescan worker is held inside the scan until released.

    The scan is where the worker is parked rather than the writer, so the
    window is torn down while the merge has not yet been decided — which is
    the state `__main__`'s `finally` actually produces.
    """

    def held_scan(_roots):
        release.wait(timeout=10)
        return FakeScanResult(
            projects=(FakeDetected(tmp_path / "roots" / "web", "web"),)
        )

    def fake_save(path, merged, *, load) -> None:
        saves.append((path, list(merged), load))

    controller = build_controller(built, [], FakeProbe())
    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=held_scan,
        now=lambda: "2026-08-14T09:00:00Z",
        save=fake_save,
    )
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        rescan=context,
        load=RegistryMissing("first run"),
    )
    qtbot.addWidget(window)
    return window


def test_a_rescan_landing_after_shutdown_writes_nothing(
    qtbot, built, tmp_path, monkeypatch
) -> None:
    """The half that costs the user something: `_apply_rescan` writes
    `projects.json` and calls `set_records` on the controller, so a merge
    arriving after teardown saved over the project list on the way out.

    INV-16's race, one pool along — and it cannot be closed by disconnecting,
    because a `QMetaCallEvent` already posted is dispatched regardless of any
    later disconnect (LWSM-1098).

    Dies on removing the `_stopped` guard from `_on_rescan_done`.
    """
    monkeypatch.setattr(mainwindow, "RESCAN_STOP_WAIT_MS", 50)
    release = threading.Event()
    saves: list = []
    window = blocking_rescan_window(qtbot, built, tmp_path, saves, release)
    try:
        window._rescan_button.click()
        qtbot.waitUntil(lambda: window._rescan_in_flight, timeout=2000)

        window.shutdown()
        release.set()
        # The worker is off the pool the window still knows about, so wait on
        # the delivery instead: three spins of the loop is more than the queued
        # slot needs and does not depend on a duration (§ T4).
        for _ in range(3):
            qtbot.wait(50)

        assert saves == [], "a rescan wrote the project list after shutdown"
    finally:
        release.set()
        assert wait_for_abandoned_probes(5000) == 0


def test_the_rescan_pool_is_unparented_when_the_wait_times_out(
    qtbot, built, tmp_path, monkeypatch
) -> None:
    """`__main__` states the rescan worker "gets the same bounded wait rather
    than being left to `~QThreadPool`, which joins with no timeout at all".

    Logging the word "abandoning" and returning does not do that: the pool stays
    parented to the window, so its destructor runs the unbounded join anyway and
    the claim is false. Abandoning it means `abandon_pool` — the same mechanism
    `ProjectController.stop()` uses, so `exit_without_waiting_for_abandoned_probes`
    covers both.

    Dies on removing the `abandon_pool(pool)` call from `shutdown()`.
    """
    monkeypatch.setattr(mainwindow, "RESCAN_STOP_WAIT_MS", 50)
    release = threading.Event()
    saves: list = []
    window = blocking_rescan_window(qtbot, built, tmp_path, saves, release)
    pool = window._rescan_pool
    try:
        window._rescan_button.click()
        qtbot.waitUntil(lambda: window._rescan_in_flight, timeout=2000)

        window.shutdown()

        assert pool.parent() is None, (
            "the abandoned pool is still owned by the window, so ~QThreadPool "
            "will join it with no timeout at destruction"
        )
        assert window._rescan_pool is None, "a second shutdown would wait again"
        assert wait_for_abandoned_probes(0) == 1, "the pool was dropped, not held"
    finally:
        release.set()
        assert wait_for_abandoned_probes(5000) == 0


# --- LWSM-1040: keyboard-first navigation ------------------------------------


def keyboard_window(qtbot, built, names, listening=(), show=False):
    """A window with one row per name, UNSHOWN unless a test asks.

    Three rows wherever a test counts them, never two. A number key selecting
    the Nth project cannot be told apart from one selecting the first or the
    last against a two-row list — the one-row-fixture trap this file has been
    caught by twice, one position along.

    Unshown is the default on purpose rather than to save a call. Every row of
    an unshown window reports `isVisible() is False`, so a test that shows the
    window cannot tell `isHidden` from `isVisible` in the number-key handler
    and a mutant swapping them survives. `setFocus` still records the window's
    focus widget while it is hidden, which is what those tests assert on; only
    `hasFocus`, which needs an ACTIVE window, forces a `show()`.
    """
    records = [record(name, 3000 + i) for i, name in enumerate(names)]
    window, controller = window_for(qtbot, built, records, FakeProbe(*listening))
    if show:
        with qtbot.waitExposed(window):
            window.show()
    return window, controller


def shown_names(window: MainWindow) -> list[str]:
    """The names still on screen, in the order the user reads them."""
    return [row._name.text() for row in window._ordered_rows() if not row.isHidden()]


def test_slash_reaches_the_filter_from_a_focused_row(qtbot, built) -> None:
    """Pressed on a row, not on the window: that is where focus actually is.

    A row ignores the key, Qt walks it up the parent chain, and the window's
    handler takes it. Sending it to the window directly would prove the handler
    exists and nothing about whether a user can reach it.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"], show=True)
    row = window._ordered_rows()[1]
    row.setFocus()
    qtbot.waitUntil(row.hasFocus, timeout=2000)

    qtbot.keyClick(row, Qt.Key.Key_Slash)

    assert window._filter.hasFocus(), (
        "`/` on a focused row must propagate to the window and focus the filter"
    )


def test_the_filter_is_a_case_insensitive_substring_of_the_name(qtbot, built) -> None:
    """Both properties in one fixture, because each hides the other's failure.

    Every letter of the fixture is load-bearing, and two mutants proved it.

    The names are MIXED case because real ones are — `LottoTracker`,
    `Ants_Projects_Hub_Website`. `BeTa` is typed in a third case again, so
    dropping `casefold()` from EITHER side leaves nothing matching: the needle
    alone reaches `beta`, which `BetaSite` and `MyBETA` do not contain, and the
    name alone reaches `betasite`, which `BeTa` does not.

    `MyBETA` also puts the match at the END of a name, so a `startswith` that
    called itself a substring match returns one row instead of two. An earlier
    fixture read `alpha/beta/betamax`, and the missing-`casefold()` mutant
    survived it twice — the second time because `eta` sits inside `BetaSite`
    in lower case whatever the surrounding letters do.
    """
    window, _ = keyboard_window(qtbot, built, ["Alpha", "BetaSite", "MyBETA"])

    qtbot.keyClicks(window._filter, "BeTa")

    assert shown_names(window) == ["BetaSite", "MyBETA"], (
        "expected both names containing 'beta' in any case, from either end"
    )


def test_escape_clears_the_filter_from_inside_the_filter(qtbot, built) -> None:
    """From inside it, because that is the case that could fail.

    Escape works here only because QLineEdit ignores it and lets it reach the
    window. Pressing it on a row would pass against a handler the filter box
    swallows, which is the arrangement a user typing a search never meets.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])
    qtbot.keyClicks(window._filter, "alp")
    assert shown_names(window) == ["alpha"], "precondition: the list is narrowed"

    qtbot.keyClick(window._filter, Qt.Key.Key_Escape)

    assert window._filter.text() == "", "Escape must empty the box, not only the list"
    assert shown_names(window) == ["alpha", "beta", "gamma"]


def test_a_number_key_counts_the_rows_still_on_screen(qtbot, built) -> None:
    """The two halves pinned against each other, because either alone is weak.

    Unfiltered, `2` landing on `beta` is satisfied by counting the dict, the
    layout or the controller's own order — all three agree, so the assertion
    cannot tell them apart. Under a filter they stop agreeing: `beta` is hidden,
    and only a count over the rows still shown puts `delta` under `2`.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma", "delta"])
    rows = window._ordered_rows()

    qtbot.keyClick(rows[0], Qt.Key.Key_2)
    assert window.focusWidget() is rows[1], "unfiltered, 2 is the second project"

    qtbot.keyClicks(window._filter, "l")
    assert shown_names(window) == ["alpha", "delta"], "precondition: beta is hidden"

    qtbot.keyClick(rows[0], Qt.Key.Key_2)
    assert window.focusWidget() is rows[3], (
        "filtered, 2 must be the second VISIBLE project, not the second row"
    )


def test_a_number_key_past_the_end_of_the_list_does_nothing(qtbot, built) -> None:
    """Three rows, `9` pressed. The focused row must not move and nothing may
    raise — an index off the end of the visible list is the ordinary case for a
    user who has just filtered the list down to one."""
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])
    row = window._ordered_rows()[0]
    row.setFocus()

    qtbot.keyClick(row, Qt.Key.Key_9)

    assert window.focusWidget() is row


def test_a_digit_typed_into_the_filter_filters_and_does_not_jump(qtbot, built) -> None:
    """The rule that lets the two mechanisms share one keyboard.

    A QLineEdit consumes a digit, so the window's handler never sees it. No
    guard in the handler says so, which is exactly why it needs a test: the
    behaviour rests on Qt's propagation rather than on a line anyone wrote.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"], show=True)
    window._filter.setFocus()
    qtbot.waitUntil(window._filter.hasFocus, timeout=2000)

    qtbot.keyClick(window._filter, Qt.Key.Key_1)

    assert window._filter.text() == "1", "the digit must be typed, not swallowed"
    assert window._filter.hasFocus(), "focus must not have jumped to a row"


def test_enter_starts_the_focused_project_and_not_another(qtbot, built) -> None:
    """Enter on the SECOND of three, so a handler wired to the wrong row fails.

    Asserted against the controller rather than the button, because clicking
    the right button on the wrong project is a bug this file has shipped before
    and a button-level assertion cannot see it.
    """
    window, controller = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])
    started: list[Path] = []
    controller.start_project = started.append
    row = window._ordered_rows()[1]

    qtbot.keyClick(row, Qt.Key.Key_Return)

    assert started == [Path("/srv/beta")], f"Enter started {started}"


def test_enter_stops_a_running_project(qtbot, built) -> None:
    """The other half of one key, and it is not symmetrical with the first.

    Enter clicks whichever of Start and Stop is enabled, so this passes only if
    `_apply_button_state`'s running case is what the key press reads. A test of
    the stopped case alone would leave the branch that picks Stop unexecuted.
    """
    window, controller = keyboard_window(
        qtbot, built, ["alpha", "beta", "gamma"], listening=(3001,)
    )
    stopped: list[Path] = []
    controller.stop_project = stopped.append
    row = window._ordered_rows()[1]
    assert row.stop_button.isEnabled(), "precondition: beta reads as running"

    qtbot.keyClick(row, Qt.Key.Key_Return)

    assert stopped == [Path("/srv/beta")], f"Enter stopped {stopped}"


def test_enter_does_nothing_while_a_project_is_in_transition(qtbot, built) -> None:
    """Both buttons are disabled during the overlay, and Enter must inherit
    that rather than restate it. A second Stop while one is in flight signals a
    group whose leader may already be reaped."""
    window, controller = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])
    row = window._ordered_rows()[1]
    row.start_button.setEnabled(False)
    row.stop_button.setEnabled(False)
    started: list[Path] = []
    stopped: list[Path] = []
    controller.start_project = started.append
    controller.stop_project = stopped.append

    qtbot.keyClick(row, Qt.Key.Key_Return)

    assert started == [] and stopped == [], (
        "Enter must not act through a disabled button"
    )


def test_filtering_hides_rows_rather_than_rebuilding_them(qtbot, built) -> None:
    """INV-13, applied to the one control where the user is certainly typing.

    A filter that tore rows down and rebuilt them would drop keyboard focus on
    every keystroke, and `design-accessibility.md § Accessibility` says the
    app never steals focus from what the user is reading.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])
    before = window._ordered_rows()

    qtbot.keyClicks(window._filter, "alp")
    qtbot.keyClick(window._filter, Qt.Key.Key_Escape)

    assert window._ordered_rows() == before, "the row widgets must be the same objects"


def test_a_project_scanned_under_an_active_filter_stays_hidden(qtbot, built) -> None:
    """A rescan lands rows into a list the user has already narrowed.

    Without the re-apply in `_sync_rows` the new project appears regardless of
    the filter, which is a list that grows while the user is reading it.
    """
    window, controller = keyboard_window(qtbot, built, ["alpha", "beta"])
    qtbot.keyClicks(window._filter, "alp")
    assert shown_names(window) == ["alpha"], "precondition"

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.set_records(
            [record("alpha", 3000), record("beta", 3001), record("gamma", 3002)]
        )
    qtbot.wait(50)

    assert shown_names(window) == ["alpha"], "the new project must respect the filter"


def test_the_filter_box_carries_an_accessible_name_of_its_own(qtbot, built) -> None:
    """`§ O8`: every interactive widget lands with an accessible name.

    Not the placeholder, which is the trap. A placeholder is erased by the
    first keystroke, so a box named only that way is announced correctly right
    up until the moment it holds something worth announcing.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"])

    qtbot.keyClicks(window._filter, "alp")

    assert window._filter.accessibleName().strip(), "the filter box is unnamed"
    assert window._filter.accessibleName() != window._filter.placeholderText()


# --- LWSM-1032: the text size the user actually reads -------------------------


def text_heights(row) -> dict[str, int]:
    """What each part of the row would PAINT at, not what it was allotted.

    `fontMetrics()` is the metric the widget draws with. Every earlier test of
    this path asserted a width the row DERIVED from its own font — which grows
    whether or not the text does, and is what let the defect below ship.
    """
    return {
        "state": row._state.fontMetrics().height(),
        "name": row._name.fontMetrics().height(),
        "port": row._port.fontMetrics().height(),
        "start": row.start_button.fontMetrics().height(),
        "open": row.open_button.fontMetrics().height(),
    }


@pytest.fixture
def app_font() -> Iterator[None]:
    """Restore the application font, which is process-wide and outlives a test."""
    app = QApplication.instance()
    assert app is not None
    original = app.font()
    yield
    app.setFont(original)


def double_the_application_font() -> None:
    app = QApplication.instance()
    assert app is not None
    font = app.font()
    font.setPointSizeF(font.pointSizeF() * 2)
    app.setFont(font)


def test_a_text_size_change_reaches_the_text_and_not_only_the_column(
    qtbot, built, app_font
) -> None:
    """`§ O8` clause 4 / `design-accessibility.md § Accessibility`'s 100-200 % control.

    LWSM-1119 found that the window's style sheet stops an application font
    change at the window: QStyleSheetStyle resolves a font onto every
    descendant, which marks it set, so no `FontChange` reaches a row. It fixed
    the window-to-row hop and left the row-to-cell hop, which fails for exactly
    the same reason — measured 2026-08-19: at 200 % the state column widened
    from 53 px to 103 px while every label and button stayed at 9 pt.

    So the assertion is on `fontMetrics()`, the metric the widget paints with.
    Three tests already covered this path and all three read a width the row
    derives from its OWN font, which grows either way. A control that enlarges
    the columns and not the words is worse than no control at all for the user
    it exists for.
    """
    window, _ = window_for(qtbot, built, [record("alpha", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    before = text_heights(row)

    double_the_application_font()
    qtbot.wait(50)

    after = text_heights(row)
    stalled = [part for part, height in after.items() if height <= before[part]]
    assert not stalled, (
        f"{stalled} did not grow with the application font "
        f"(before={before}, after={after}) — the text size control moves the "
        "layout and not the text"
    )


def test_the_filter_box_grows_with_the_text_too(qtbot, built, app_font) -> None:
    """The chrome is not exempt. The filter box is the one control a magnifier
    user reaches for first (LWSM-1040), and it sits outside the row loop that
    LWSM-1119's fix walked — so a fix that only re-pushes the font to rows
    leaves the box the user is typing into at 9 pt."""
    window, _ = window_for(qtbot, built, [record("alpha", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    before = window._filter.fontMetrics().height()

    double_the_application_font()
    qtbot.wait(50)

    assert window._filter.fontMetrics().height() > before


def test_a_row_added_after_the_change_is_born_at_the_new_size(
    qtbot, built, app_font
) -> None:
    """A rescan creates rows after the change, so the list holds rows built on
    both sides of it and they must render at the same size.

    Measured 2026-08-19, and the direction is the opposite of the guess: a
    fresh row is ALREADY correct at 33 px, because it inherits from a parent
    whose font is explicitly set, while the row that existed at the time was
    the stale one at 17 px. So this locks the agreement rather than the new
    row — which is the property a user sees, a list where half the rows are
    half the size being the visible symptom either way round."""
    window, controller = window_for(qtbot, built, [record("alpha", 5005)], FakeProbe())
    with qtbot.waitExposed(window):
        window.show()
    double_the_application_font()
    qtbot.wait(50)
    grown = text_heights(rows_of(window)[0])["state"]

    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.set_records([record("alpha", 5005), record("beta", 5006)])
    qtbot.wait(50)

    fresh = [row for row in rows_of(window) if row._name.text() == "beta"][0]
    assert text_heights(fresh)["state"] == grown, (
        "a row created after the text-size change was born at the old size"
    )


# --- LWSM-1032: the in-app text-size control ----------------------------------


def scaled_window(qtbot, built, **kwargs):
    controller = build_controller(built, [record("alpha", 5005)], FakeProbe(5005))
    window = MainWindow(controller, Theme.default(), [], **kwargs)
    qtbot.addWidget(window)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    return window, controller


def test_the_bar_offers_every_step_of_the_text_size_range(
    qtbot, built, app_font
) -> None:
    """`design-accessibility.md § Accessibility`: 100 % to 200 %, in-app and
    independent of the desktop's own scaling.

    The steps are asserted as a whole rather than "at least 100 and 200",
    because a control offering only the two ends is not a text-size control —
    the user who needs 150 % is the user this item exists for.
    """
    window, _ = scaled_window(qtbot, built)

    labels = [action.text() for action in window._text_size_actions.values()]

    assert list(window._text_size_actions) == [100, 125, 150, 175, 200]
    assert all("%" in label for label in labels), labels
    assert "&" in window._text_size_menu.title(), "the submenu needs a mnemonic"


def test_choosing_a_size_enlarges_the_text_the_user_reads(
    qtbot, built, app_font
) -> None:
    """Through the menu action, not through `set_text_scale`, so the wiring is
    covered too: a picker that computes the right size and is connected to
    nothing looks identical from inside the method."""
    window, _ = scaled_window(qtbot, built)
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    before = text_heights(row)

    window._text_size_actions[200].trigger()
    qtbot.wait(50)

    after = text_heights(row)
    assert all(after[part] > before[part] for part in before), (before, after)


def test_the_scale_multiplies_the_desktop_font_and_does_not_compound(
    qtbot, built, app_font
) -> None:
    """The one arithmetic bug this shape invites: scaling the CURRENT font each
    time, so 150 % then 200 % lands at 300 % and returning to 100 % never gets
    back. Every step is against the size the desktop gave us."""
    window, _ = scaled_window(qtbot, built)
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    original = text_heights(row)["state"]

    window._text_size_actions[150].trigger()
    qtbot.wait(20)
    window._text_size_actions[200].trigger()
    qtbot.wait(20)
    at_200 = text_heights(row)["state"]
    window._text_size_actions[100].trigger()
    qtbot.wait(20)

    assert text_heights(row)["state"] == original, "100 % must be where we started"
    assert at_200 < original * 3, "the steps compounded instead of replacing"


def test_a_stored_size_is_applied_at_construction_and_shown_as_checked(
    qtbot, built, app_font
) -> None:
    """A restored scale arrives with no action triggered, so the checkmark has
    to be set from the value — the same rule `set_theme` follows for a theme
    restored from settings.json."""
    plain, _ = scaled_window(qtbot, built)
    with qtbot.waitExposed(plain):
        plain.show()
    at_100 = text_heights(rows_of(plain)[0])["state"]
    plain.close()

    window, _ = scaled_window(qtbot, built, text_scale=175)
    with qtbot.waitExposed(window):
        window.show()

    assert text_heights(rows_of(window)[0])["state"] > at_100
    assert window._text_size_actions[175].isChecked()
    assert not window._text_size_actions[100].isChecked()


def test_the_chosen_size_is_handed_to_the_saver(qtbot, built, app_font) -> None:
    saved: list[int] = []
    window, _ = scaled_window(qtbot, built, save_text_scale=saved.append)

    window._text_size_actions[150].trigger()

    assert saved == [150]


def test_a_size_that_cannot_be_saved_is_reported_and_still_applied(
    qtbot, built, app_font
) -> None:
    """The same rule as the theme: a settings file that cannot be written must
    not undo a change the user can already see happen."""

    def refuse(_scale: int) -> None:
        raise SettingsError("nowhere to write")

    window, _ = scaled_window(qtbot, built, save_text_scale=refuse)
    with qtbot.waitExposed(window):
        window.show()
    before = text_heights(rows_of(window)[0])["state"]

    window._text_size_actions[200].trigger()
    qtbot.wait(50)

    assert text_heights(rows_of(window)[0])["state"] > before
    assert "nowhere to write" in window.statusBar().currentMessage()


def test_restoring_a_stored_size_writes_nothing(qtbot, built, app_font) -> None:
    """Construction applies the stored scale with `remember=False`. Without
    that, every start rewrites settings.json to the value it just read — a
    write on a read path, which turns an unwritable config directory into a
    status-bar complaint on a launch where the user changed nothing."""
    saved: list[int] = []

    scaled_window(qtbot, built, text_scale=150, save_text_scale=saved.append)

    assert saved == []


# --- LWSM-1032: design-accessibility.md § Accessibility's check table ------

# `MIN_TARGET_PX` is imported at the top of this file, never re-stated here:
# the source clamps its button widths to that floor, and a copy would let the
# two drift while this test went on passing against whatever the source chose.


def clickable(window: MainWindow) -> dict[str, object]:
    """Every widget a pointer can activate, named for a readable failure."""
    from PySide6.QtWidgets import QAbstractButton, QLineEdit

    found: dict[str, object] = {}
    for widget in window.findChildren(QAbstractButton) + window.findChildren(QLineEdit):
        if not widget.isVisibleTo(window):
            continue
        label = widget.text() if hasattr(widget, "text") else ""
        found[f"{type(widget).__name__}({label or widget.accessibleName()})"] = widget
    return found


@pytest.mark.parametrize("base_point_size", [None, 6.0])
def test_every_clickable_target_clears_the_floor_and_grows_with_the_text(
    qtbot, built, app_font, base_point_size
) -> None:
    """Two properties in one test on purpose: a target can clear 24x24 by being
    a fixed size, which is the failure the second half names. `§ O7` forbids
    the pixel constant that would produce it, and this is what checks the rule
    was actually followed at every call site rather than at most of them.

    **Parametrised over the SYSTEM font, because the ambient one hid the bug.**
    A button's height comes from the style, which derives it from the font, so
    this machine's default produced 25 px — clearing the floor by one pixel —
    and CI's smaller default produced 22. The floor was breached on the
    runner and nowhere else, which means it was breached for any user with a
    small system font and this suite could not see it. 6 pt is well under any
    plausible desktop setting, so the parametrised case fails on a build with
    no explicit floor whatever machine it runs on.
    """
    if base_point_size is not None:
        app = QApplication.instance()
        assert app is not None
        font = app.font()
        font.setPointSizeF(base_point_size)
        app.setFont(font)
    window, _ = scaled_window(qtbot, built)
    with qtbot.waitExposed(window):
        window.show()

    targets = clickable(window)
    assert targets, "no clickable widget was found — the test is measuring nothing"
    too_small = {
        name: widget.size()
        for name, widget in targets.items()
        if widget.width() < MIN_TARGET_PX or widget.height() < MIN_TARGET_PX
    }
    assert not too_small, f"below {MIN_TARGET_PX}x{MIN_TARGET_PX} at 100 %: {too_small}"

    before = {name: widget.height() for name, widget in targets.items()}
    window._text_size_actions[200].trigger()
    qtbot.wait(50)

    stalled = {
        name: (before[name], widget.height())
        for name, widget in targets.items()
        if widget.height() <= before[name]
    }
    assert not stalled, f"fixed at 200 % while the text around them grew: {stalled}"


def test_the_state_word_comes_first_in_the_row(qtbot, built) -> None:
    """`design-accessibility.md § Accessibility`: the word must be FIRST in the row, not
    merely present in it. A magnifier shows a small window onto the screen, so
    what the lens lands on when it reaches the row is the whole of what the
    user gets for free.

    Asserted against every other cell AND every button, because the buttons
    are what a "state on the right" layout would put in front of it.
    """
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()

    for row in rows_of(window):
        state_x = row._state.geometry().left()
        others = {
            "name": row._name,
            "port": row._port,
            "start": row.start_button,
            "stop": row.stop_button,
            "restart": row.restart_button,
            "open": row.open_button,
        }
        ahead = {
            name: widget.geometry().left()
            for name, widget in others.items()
            if widget.geometry().left() <= state_x
        }
        assert not ahead, f"{ahead} sit at or before the state word at x={state_x}"


def test_the_whole_row_including_its_controls_fits_one_lens_view(qtbot, built) -> None:
    """The band is `READABLE_BAND_PX`, and the promise covers "name, state,
    port and controls" — the controls being the half an earlier test left out,
    and the half furthest right.

    The name is `known-issue-011`'s own: `customer-dashboard-frontend-v2` is
    what that issue measured the band breaking on (port cell at 630 px on
    2026-08-07), so it is the fixture that has actually failed here. A budget
    that only holds for `a` is not a budget, and one checked against a shorter
    name than the one on record is the same mistake one letter along.
    """
    window, _ = window_for(
        qtbot,
        built,
        [record("customer-dashboard-frontend-v2", 5005)],
        FakeProbe(5005),
    )
    with qtbot.waitExposed(window):
        window.show()
    window.resize(1400, window.height())
    qtbot.waitUntil(lambda: window.width() == 1400, timeout=2000)
    row = rows_of(window)[0]

    right_edge = row.open_button.geometry().right()
    assert right_edge <= READABLE_BAND_PX, (
        f"the row's controls end at x={right_edge}, outside the "
        f"{READABLE_BAND_PX} px lens the user has to read it through"
    )


def test_nothing_important_is_discoverable_only_by_hovering(qtbot, built) -> None:
    """`design-accessibility.md § Accessibility`: hover states are easy to miss at
    magnification and impossible to discover by keyboard, so every affordance
    is visible at rest.

    Read as: at rest, with no pointer anywhere near it, every control already
    says what it is. An icon-only button carrying its meaning in a tooltip is
    what this fails on.
    """
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()

    unnamed = [
        name
        for name, widget in clickable(window).items()
        if not (getattr(widget, "text", lambda: "")() or widget.accessibleName())
    ]
    assert not unnamed, f"say nothing until hovered: {unnamed}"

    for menu in (window._file_menu, window._settings_menu):
        for action in menu.actions():
            if action.isSeparator():
                continue
            assert action.text(), f"an unnamed entry in {menu.title()}"


def test_no_animation_conveys_anything_and_none_is_created(qtbot, built) -> None:
    """`design-accessibility.md § Accessibility`: no animation conveys
    information, and any decorative one honours reduce-motion.

    There is no reduce-motion preference to set because there is nothing to
    suppress — so the check is that the count stays zero across a real state
    change, the moment an animation would be reached for. A later item that
    adds one has to answer the preference here, which is the point: this fails
    the day the promise stops being free.
    """
    from PySide6.QtCore import QAbstractAnimation

    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    with qtbot.waitExposed(window):
        window.show()

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    qtbot.wait(50)

    animations = window.findChildren(QAbstractAnimation)
    assert not animations, f"an animation was created: {animations}"


def test_no_widget_pins_a_font_family_or_a_pixel_size(qtbot, built) -> None:
    """`design-accessibility.md § Accessibility`: the desktop's font family and size are
    honoured, and the in-app control multiplies them rather than replacing
    them.

    A pixel size is the specific failure: it ignores the desktop's own DPI
    scaling, and `QFont.pixelSize()` returns -1 for a point-sized font, so the
    check is exact rather than a heuristic. The style sheet is checked too,
    because a `font-size:` there would pin every widget at once and no
    per-widget property would show it.
    """
    from PySide6.QtWidgets import QWidget

    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    app = QApplication.instance()
    assert app is not None

    pinned = {
        f"{type(widget).__name__}: {widget.font().family()}"
        for widget in window.findChildren(QWidget)
        if widget.font().pixelSize() != -1
        or widget.font().family() != app.font().family()
    }
    assert not pinned, f"these pin their own font: {sorted(pinned)}"
    assert "font-" not in window.styleSheet(), "the style sheet pins a font"


def test_nothing_is_clipped_at_two_hundred_percent(qtbot, built, app_font) -> None:
    """`testing.md § T8`'s fourth check, and the one that could not be written
    until the control existed.

    Every cell must be at least as wide as the text it holds. A `QLabel` does
    not elide by default, it CLIPS — so the failure is silent, and the last
    characters of a project's name simply are not there.
    """
    window, _ = window_for(
        qtbot,
        built,
        [record("Ants_Projects_Hub_Website", 5005), record("b", None)],
        FakeProbe(5005),
    )
    with qtbot.waitExposed(window):
        window.show()

    window._text_size_actions[200].trigger()
    qtbot.wait(50)

    clipped = {}
    for row in rows_of(window):
        for name, label in (
            ("state", row._state),
            ("name", row._name),
            ("port", row._port),
        ):
            needs = label.fontMetrics().horizontalAdvance(label.text())
            if needs > label.width():
                clipped[f"{row._name.text()}.{name}"] = (needs, label.width())
        for button in (row.start_button, row.stop_button, row.open_button):
            if button.sizeHint().width() > button.width():
                clipped[f"{row._name.text()}.{button.text()}"] = (
                    button.sizeHint().width(),
                    button.width(),
                )
    assert not clipped, f"clipped at 200 % (needs, has): {clipped}"


STATE_CELL_WIDTH_PX = 120
"""A column width wide enough for every state word, applied to all five rows so
their geometry is identical and only the rendering differs."""


def state_ink(row: ProjectRow) -> bytes:
    """The state cell as a colour-blind user sees it: ink, or no ink.

    Greyscale ALONE is not the check, and the first draft learned it the hard
    way. Two colours of different luminance map to two different greys, so a
    "the images differ" assertion passes for a state told apart by colour and
    nothing else — which is the exact promise it was written to hold. Every
    pixel is therefore thresholded to 1 or 0, which collapses hue and
    brightness together and leaves only the SHAPES: the word and the glyph.

    (The band's width had a second, dumber version of the same fault: at
    200 px it reached the Start button, whose enablement differs by state, so
    the comparison was of button greying rather than of the state cell.)

    Thresholded at mid-grey against the default palette, which is dark, so ink
    is the bright half. A state token too dark to cross it against that
    background would fail `test_theme.py`'s contrast floor first.
    """
    from PySide6.QtGui import QImage

    image = row.grab().toImage().convertToFormat(QImage.Format.Format_Grayscale8)
    band = image.copy(0, 0, row._state.geometry().right() + 1, image.height())
    return bytes(1 if value > 128 else 0 for value in bytes(band.constBits()))


def test_every_state_is_readable_with_no_colour_at_all(qtbot) -> None:
    """`design-accessibility.md § Accessibility`: the commonest colour
    blindness is exactly red/green, so every state carries three signals —
    the word, a distinct glyph, and colour. The blunt form of that promise is
    this one: with the colour taken away, no two states may render alike.

    Five rows built identically but for the status, so the word and the glyph
    are the only variables. Two states sharing both would pass every check in
    `test_theme.py` — which is arithmetic over the palette and cannot see what
    is painted with it — and fail here.
    """
    from lwsm.controller import RowView

    inks: dict[ProjectStatus, bytes] = {}
    for status in ProjectStatus:
        row = ProjectRow(
            RowView(
                path=Path("/srv/a"),
                name="a",
                effective_port=5005,
                status=status,
                managed=True,
            ),
            Theme.default(),
        )
        qtbot.addWidget(row)
        # One shared column geometry, so the cell compared is the same
        # rectangle in every image and the only variable left is the painting.
        row.apply_column_widths((STATE_CELL_WIDTH_PX,) * 3)
        row.resize(STATE_CELL_WIDTH_PX * 6, row.sizeHint().height())
        inks[status] = state_ink(row)

    alike = [
        (one.name, other.name)
        for index, one in enumerate(inks)
        for other in list(inks)[index + 1 :]
        if inks[one] == inks[other]
    ]
    assert not alike, f"indistinguishable without colour: {alike}"


def tab_stops(window: MainWindow) -> list:
    """Every widget Tab lands on, in the order Tab reaches them.

    Walked with `nextInFocusChain` rather than by sending Tab keys: a key needs
    an active window, which an offscreen platform will not always give, and the
    chain is what Qt itself walks when the key arrives.
    """
    stops = []
    widget = window
    for _ in range(500):  # a cycle guard; the chain is circular by construction
        widget = widget.nextInFocusChain()
        if widget is window:
            break
        if (
            widget.isVisible()
            and widget.isEnabled()
            and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
        ):
            stops.append(widget)
    return stops


def test_every_action_is_reachable_by_tab_in_the_order_it_is_read(qtbot, built) -> None:
    """`testing.md § T8`'s second check, both halves of it.

    Reachability alone is not the promise — "tab order matches visual order"
    is the half that decides whether a magnifier user can predict where the
    focus went, and a chain that jumps the lens back and forth across the
    window is a chain they have to hunt along.

    Two rows, because a per-row ordering bug cannot appear in one.
    """
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()

    stops = tab_stops(window)
    reachable = set(stops)
    unreachable = [
        name
        for name, widget in clickable(window).items()
        if widget.isEnabled() and widget not in reachable
    ]
    assert not unreachable, f"no Tab reaches these: {unreachable}"

    positions = [
        (widget.mapTo(window, QPoint(0, 0)).y(), widget.mapTo(window, QPoint(0, 0)).x())
        for widget in stops
    ]
    walked = [
        (widget.accessibleName() or type(widget).__name__, where)
        for widget, where in zip(stops, positions, strict=True)
    ]
    assert positions == sorted(positions), (
        f"tab order does not follow visual order: {walked}"
    )


def test_every_interactive_widget_has_a_name_a_screen_reader_can_read(
    qtbot, built
) -> None:
    """`testing.md § T8`'s third check, asked of the ACCESSIBILITY TREE rather
    than of `accessibleName()`.

    The two are not the same question, and LWSM-1071 is the record of what the
    difference costs: `setAccessibleName("")` left a label announced anyway,
    because `QAccessibleDisplay` falls back to `QLabel::text()`. Read the other
    way round — as here — a button whose `accessibleName()` is empty may still
    announce its label perfectly well, and failing it would be a false alarm.
    """
    from PySide6.QtGui import QAccessible

    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()

    unnamed = []
    for name, widget in clickable(window).items():
        interface = QAccessible.queryAccessibleInterface(widget)
        if interface is None or not interface.text(QAccessible.Text.Name).strip():
            unnamed.append(name)
    assert not unnamed, f"a screen reader finds these unnamed: {unnamed}"


def test_a_failure_is_reported_on_the_row_that_raised_it(qtbot, built) -> None:
    """`design-accessibility.md § Accessibility`: "a message in a far-off status bar is
    invisible to someone whose lens is on a button", so feedback surfaces next
    to the row or control that caused it.

    The assertion is on the RECTANGLES, not on which widget was handed the
    text: a label that is inside the row and hidden overlaps nothing, and a
    label placed correctly but off-screen would pass any parenthood check.

    Two rows, because the interesting failure is the message landing on the
    wrong one — which a one-row fixture cannot see (this file, twice).
    """
    window, controller = window_for(qtbot, built, two_rows(), FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    first, second = rows_of(window)

    controller.action_failed.emit(second._view.path, "it would not start")
    qtbot.wait(20)

    where = second.error_rect()
    assert where is not None, "the failure is not shown on the row at all"
    assert where.intersects(QRect(second.mapToGlobal(QPoint(0, 0)), second.size())), (
        f"the message at {where} does not overlap the row that raised it"
    )
    assert first.error_rect() is None, "the message landed on the wrong row too"


def test_the_failure_clears_when_the_row_moves_on(qtbot, built) -> None:
    """A stale error beside a project that has since started is a lie, and a
    magnifier user reading one row at a time has nothing else on screen to
    contradict it."""
    probe = FakeProbe()
    window, controller = window_for(qtbot, built, [record("a", 5005)], probe)
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    controller.action_failed.emit(row._view.path, "it would not start")
    qtbot.wait(20)
    assert row.error_rect() is not None, "precondition"

    probe.listening.add(5005)
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    qtbot.wait(20)

    assert row.error_rect() is None, "the error outlived the state it described"


def test_a_failure_for_no_particular_project_still_reaches_the_user(
    qtbot, built
) -> None:
    """Not every failure has a row — a path that has since been removed, or a
    message about the manager rather than a project. The status bar stays the
    channel for those, so widening the signal cannot lose one."""
    window, controller = window_for(qtbot, built, two_rows(), FakeProbe(5005))

    controller.action_failed.emit(Path("/srv/gone"), "nothing to start it with")
    qtbot.wait(20)

    assert "nothing to start it with" in window.statusBar().currentMessage()


def test_the_failure_is_announced_and_leaves_nothing_unnamed_behind(
    qtbot, built
) -> None:
    """Two halves of one rule, and the second is LWSM-1071 arriving from the
    other direction.

    A shown failure must reach a screen reader — it is the row's own text, so
    it belongs in the tree. And a CLEARED one must leave nothing there: a
    hidden QLabel is still a child, named `''`, which is the unnamed child
    LWSM-1071 spent an item removing. That is why the label is created on
    demand and destroyed rather than hidden, and this is the test that fails
    if someone simplifies it back to `hide()`.
    """
    window, controller = window_for(qtbot, built, [record("a", 5005)], FakeProbe(5005))
    with qtbot.waitExposed(window):
        window.show()
    row = rows_of(window)[0]
    before = accessible_children(row)
    assert "" not in before, before

    controller.action_failed.emit(row._view.path, "it would not start")
    qtbot.wait(20)
    assert "it would not start" in accessible_children(row)

    row.clear_error()
    qtbot.wait(20)

    after = accessible_children(row)
    assert "" not in after, f"an unnamed child was left behind: {after}"
    assert after == before


def test_a_poll_during_editing_does_not_steal_the_focus_or_the_caret(
    qtbot, built
) -> None:
    """`design-accessibility.md § Accessibility`: "the app never steals focus
    from what the user is reading".

    Driven while the user is TYPING, which is the design's own wording and the
    case that matters: the poll runs once a second and rebuilds nothing, but a
    `_sync_rows` that touched the focus would move the caret out of the filter
    box between two keystrokes.

    `test_focus_survives_a_status_change` looks adjacent and is not this: it
    asserts the row widget was not REBUILT, and never checks where the focus
    went — measured 2026-08-19, it calls `setFocus()` and then asserts only
    identity and the rendered word.
    """
    probe = FakeProbe(5005)
    window, controller = window_for(qtbot, built, two_rows(), probe)
    with qtbot.waitExposed(window):
        window.show()
    window._filter.setFocus()
    qtbot.waitUntil(window._filter.hasFocus, timeout=2000)
    qtbot.keyClicks(window._filter, "al")
    caret = window._filter.cursorPosition()

    probe.listening.clear()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    qtbot.wait(20)

    assert window._filter.hasFocus(), (
        f"the poll moved the focus to {window.focusWidget()}"
    )
    assert window._filter.cursorPosition() == caret
    assert window._filter.text() == "al"


def test_a_confirmation_lands_over_the_list_and_blocks_the_whole_app(
    qtbot, built, monkeypatch
) -> None:
    """`design-accessibility.md § Accessibility`'s confirmation row, both halves.

    The real `_confirm_dialog`, not the injected `confirm` seam: the seam
    exists so tests never open a modal, and this is the one test that has to
    look at the thing the seam stands in for. `exec()` is replaced rather than
    called — a real one blocks the loop with nothing to click it.

    **The modality half is the half that matters and the half that was wrong
    in the document.** "Modal to the window" is Qt's `WindowModal`, which
    blocks `MainWindow` alone and leaves the tray's per-project start/stop menu
    live while a trust prompt waits. Asserted as `ApplicationModal` — which
    `QMessageBox` is from construction, so this pins a property rather than
    demanding one.

    **The rect half is deliberately weaker than it looks**, and the doc says so
    too: it is an assertion about Qt's own centring, taken headless. Under
    Wayland placement is the compositor's (ADR-0007), so this cannot speak for
    the target platform — it catches a dialog centred on the wrong widget, not
    a compositor that puts it elsewhere.

    Four rows, because at one row "overlaps the list" is true of any dialog
    that overlaps anything, and the promise would read as satisfied by
    accident.

    **Mutants run, and one survived on purpose.** Setting
    `WindowModality.WindowModal` kills this test. Replacing the parent with
    `QMessageBox(None)` does NOT — an unparented box still lands over the list
    under `offscreen`. That is the contract, not a hole in the test: the check
    row forbids asserting the parent ("the *result*, never that a parent was
    passed"), because ADR-0007 makes parentage unobservable on the target
    platform. So the modality half is what carries this test, and the rect half
    is a floor.
    """
    from PySide6.QtWidgets import QMessageBox

    window, _ = window_for(
        qtbot,
        built,
        [record(f"p{index}", 5000 + index) for index in range(4)],
        FakeProbe(),
    )
    with qtbot.waitExposed(window):
        window.show()

    seen: dict[str, object] = {}

    def capture(box: QMessageBox) -> QMessageBox.StandardButton:
        box.show()
        QApplication.processEvents()
        seen["rect"] = QRect(box.mapToGlobal(QPoint(0, 0)), box.size())
        seen["modality"] = box.windowModality()
        box.hide()
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "exec", capture)

    answered = window._confirm_dialog(
        Path("/srv/p0"), "/srv/p0/start.sh", ("./start.sh",)
    )

    assert answered is False, "No is the default and this test answered No"
    assert seen["modality"] == Qt.WindowModality.ApplicationModal, (
        "a window-modal trust prompt leaves the tray's start menu live"
    )
    rows = rows_of(window)
    listing = QRect(rows[0].mapToGlobal(QPoint(0, 0)), rows[0].size())
    for row in rows[1:]:
        listing = listing.united(QRect(row.mapToGlobal(QPoint(0, 0)), row.size()))
    assert seen["rect"].intersects(listing), (
        f"the confirmation at {seen['rect']} lands away from the list {listing}"
    )


# --- LWSM-1148: exporting a profile, and merging one back in -----------------


def profile_window(
    qtbot,
    built,
    records,
    tmp_path: Path,
    *,
    to_save: str | None = None,
    to_open: str | None = None,
    load=None,
    saves: list | None = None,
) -> tuple[MainWindow, ProjectController]:
    """A window whose registry is reachable and whose file dialogs are fakes.

    Both pickers are injected in every test here for `SettingsDialog`'s reason:
    a real `QFileDialog` blocks the event loop with nobody to click it, which
    is a hang rather than a failure.
    """
    controller = build_controller(built, list(records), FakeProbe())

    def fake_save(path, merged, *, load) -> None:
        if saves is not None:
            saves.append((path, list(merged), load))

    context = mainwindow.RescanContext(
        projects_path=tmp_path / "projects.json",
        roots=(tmp_path / "roots",),
        scan=lambda _roots: scanner.ScanResult(
            projects=(), timed_out=False, unlistable_roots=()
        ),
        now=lambda: "2026-08-21T09:00:00Z",
        save=fake_save,
    )
    window = MainWindow(
        controller,
        Theme.default(),
        [],
        rescan=context,
        load=load if load is not None else LoadResult([], [], 0),
        choose_profile_to_save=lambda: to_save,
        choose_profile_to_open=lambda: to_open,
    )
    qtbot.addWidget(window)
    return window, controller


def test_the_file_menu_offers_export_and_import(qtbot, built, tmp_path) -> None:
    """Asserted as the whole list, like the Settings menu beside it, so an
    entry added without a decision about its placement lands here."""
    window, _ = profile_window(qtbot, built, two_rows(), tmp_path)

    assert entry_texts(window._file_menu) == [
        "&Rescan projects",
        "&Export profile...",
        "&Import profile...",
        "&Quit",
    ]
    assert all("&" in text for text in entry_texts(window._file_menu))


def test_the_profile_entries_are_absent_without_a_registry(qtbot, built) -> None:
    """Both or neither. Exporting needs the `LoadResult` its gate reads and
    importing needs somewhere to write back to, so a window holding neither
    gets no entry rather than one that reports a failure when chosen."""
    window, _ = window_for(qtbot, built, two_rows(), FakeProbe(5005))

    assert window._export_action is None
    assert window._import_action is None
    assert "&Export profile..." not in entry_texts(window._file_menu)


def test_export_writes_a_profile_that_loads_back(qtbot, built, tmp_path) -> None:
    """End to end through the seam: the file the picker named holds exactly
    the controller's records."""
    profile = tmp_path / "saved.json"
    records = two_rows()
    window, _ = profile_window(qtbot, built, records, tmp_path, to_save=str(profile))

    window._export_action.trigger()

    assert registry.load_projects(profile).records == records
    assert str(profile) in window.statusBar().currentMessage()


def test_a_cancelled_export_writes_nothing(qtbot, built, tmp_path) -> None:
    """The picker returning None is the user pressing Cancel, and it must not
    reach the writer or the status bar."""
    window, _ = profile_window(qtbot, built, two_rows(), tmp_path, to_save=None)

    window._export_action.trigger()

    assert list(tmp_path.glob("*.json")) == []
    assert window.statusBar().currentMessage() == ""


def test_an_export_refusal_reaches_the_status_bar(qtbot, built, tmp_path) -> None:
    """A refused export must SAY so. A silent one leaves the user believing
    they hold a known-good configuration they do not have."""
    window, _ = profile_window(
        qtbot,
        built,
        two_rows(),
        tmp_path,
        to_save=str(tmp_path / "saved.json"),
        load=LoadResult(records=[], reasons=["bad row"], rows_refused=1),
    )

    window._export_action.trigger()

    message = window.statusBar().currentMessage()
    assert "Profile not saved" in message
    assert "incomplete" in message
    assert not (tmp_path / "saved.json").exists()


def write_profile(tmp_path: Path, projects: list[dict]) -> Path:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"schema_version": 1, "projects": projects}), encoding="utf-8"
    )
    return profile


def test_import_restores_the_user_half_saves_it_and_updates_the_controller(
    qtbot, built, tmp_path
) -> None:
    """The three things an import has to do, asserted together — a merge that
    is computed and never written is the shape LWSM-1136 shipped."""
    saves: list = []
    profile = write_profile(
        tmp_path,
        [{"path": "/srv/a", "name": "a-from-profile", "port_override": 9100}],
    )
    window, controller = profile_window(
        qtbot, built, two_rows(), tmp_path, to_open=str(profile), saves=saves
    )

    window._import_action.trigger()

    restored = controller.records()[0]
    assert restored.name == "a-from-profile"
    assert restored.port_override == 9100
    # The detected half stays this machine's.
    assert restored.port == 5005
    assert len(saves) == 1
    assert saves[0][1] == controller.records()
    assert "Import:" in window.statusBar().currentMessage()


def test_an_import_is_refused_when_the_profile_had_any_refusal(
    qtbot, built, tmp_path
) -> None:
    """The guarantee `_user_half_applied` rests on, and the reason it needs no
    per-field qualifier.

    A field refusal keeps the row and drops the field, so a profile with one
    hand-typed `"port_override": "9100"` would otherwise restore a user half
    with a hole in it — writing `None` over a stored override, which is the
    exact defect the LWSM-1007 gate caught on the rescan merge.
    """
    saves: list = []
    profile = write_profile(
        tmp_path, [{"path": "/srv/a", "name": "a", "port_override": "9100"}]
    )
    window, controller = profile_window(
        qtbot, built, two_rows(), tmp_path, to_open=str(profile), saves=saves
    )
    before = controller.records()

    window._import_action.trigger()

    assert controller.records() == before
    assert saves == []
    assert "Profile not loaded" in window.statusBar().currentMessage()


def test_an_unreadable_profile_is_refused(qtbot, built, tmp_path) -> None:
    """`load_projects` raising is reported, never allowed to escape a menu
    trigger — PySide6 swallows what escapes a slot."""
    profile = tmp_path / "profile.json"
    profile.write_text("{not json", encoding="utf-8")
    saves: list = []
    window, controller = profile_window(
        qtbot, built, two_rows(), tmp_path, to_open=str(profile), saves=saves
    )
    before = controller.records()

    window._import_action.trigger()

    assert controller.records() == before
    assert saves == []
    assert "Profile not loaded" in window.statusBar().currentMessage()


def test_a_cancelled_import_changes_nothing(qtbot, built, tmp_path) -> None:
    saves: list = []
    window, controller = profile_window(
        qtbot, built, two_rows(), tmp_path, to_open=None, saves=saves
    )
    before = controller.records()

    window._import_action.trigger()

    assert controller.records() == before
    assert saves == []
    assert window.statusBar().currentMessage() == ""


def test_import_is_disabled_while_a_rescan_is_in_flight(qtbot, built, tmp_path) -> None:
    """Not tidiness: a rescan that started first writes last, so an imported
    user half would be silently dropped by it. Export is left alone because it
    only reads.

    This drives `_set_rescan_enabled`, which is the one place the flight state
    reaches any control; that the rescan flow calls it is pinned by the button
    tests above.
    """
    window, _ = profile_window(qtbot, built, two_rows(), tmp_path)

    window._set_rescan_enabled(False)
    assert not window._import_action.isEnabled()
    assert window._export_action.isEnabled()

    window._set_rescan_enabled(True)
    assert window._import_action.isEnabled()


def test_the_profile_entries_retranslate(qtbot, built, tmp_path) -> None:
    """`LanguageChange` has one place to go, and an entry added outside
    `_retranslate_menus` keeps its construction-time empty text."""
    window, _ = profile_window(qtbot, built, two_rows(), tmp_path)

    window._export_action.setText("")
    window._import_action.setText("")
    window.changeEvent(QEvent(QEvent.Type.LanguageChange))

    assert window._export_action.text() == "&Export profile..."
    assert window._import_action.text() == "&Import profile..."


# --- LWSM-1033: window geometry and Centre on screen (ADR-0007) --------------
#
# ADR-0007 is explicit that the verification here is BEHAVIOURAL: these assert
# where the window ENDS UP, never that `move()` or `dbus-send` was called. A
# test asserting the call is exactly the test that passes while OneUp's window
# opens in the wrong place, which is the failure the ADR exists to avoid.
#
# The Wayland branch cannot have a real compositor in the suite, so `fake_kwin`
# stands in for KWin: it reads the script the real `run_kwin_script` wrote,
# parses the coordinates out of it, and applies them. Everything up to the
# D-Bus call is this project's own code — the clamp, the script, the temporary
# file — so what is faked is the compositor, not the mechanism.


def geometry_window(qtbot, built, records, **kwargs) -> MainWindow:
    """A window built with LWSM-1033's seams and actually shown.

    Shown, because `_restore_geometry` runs off the first `showEvent` and a
    window that is never shown restores nothing. `waitExposed` is what makes
    the deferred single-shot actually fire.

    **And polled, in that order, because the real app does both.** Without the
    poll no rows ever arrive, so `_apply_default_geometry` returns early and
    every test here silently measures `_restore_geometry` alone — which is
    what a mutation of the remembered-size preference proved on 2026-08-21 by
    surviving the whole suite. A fixture that cannot reach half the mechanism
    reads exactly like a mechanism that is untested.
    """
    controller = build_controller(built, records, FakeProbe(5005))
    window = MainWindow(controller, Theme.default(), [], **kwargs)
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    qtbot.wait(1)
    return window


def wayland_place(applied: list[Rect]):
    """`place_window` with a stand-in for KWin, driven as a Wayland session."""

    def fake_kwin(argv: list[str], **_kwargs: object) -> None:
        for arg in argv:
            if arg.startswith("string:") and arg.endswith(".js"):
                script = Path(arg[len("string:") :]).read_text()
                found = dict(re.findall(r"([xy]): (-?\d+),", script))
                applied.append(Rect(int(found["x"]), int(found["y"]), 0, 0))

    return functools.partial(
        placement.place_window,
        environ={"XDG_SESSION_TYPE": "wayland"},
        which=lambda _name: "/usr/bin/dbus-send",
        run=fake_kwin,
    )


def test_the_window_reopens_at_the_remembered_position_off_wayland(
    qtbot, built
) -> None:
    """The behaviour the user named, on the branch where `move()` is honoured.

    Asserted on `pos()` rather than `geometry()`: `pos()` is the frame's corner
    and is what `move` sets, and the two differ by the decoration. Storing one
    and restoring through the other is what walks the window across the desktop
    a few pixels per launch.
    """
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(137, 219),
        size=(640, 480),
        place=functools.partial(
            placement.place_window, environ={"XDG_SESSION_TYPE": "x11"}
        ),
    )

    assert (window.pos().x(), window.pos().y()) == (137, 219)
    assert (window.width(), window.height()) == (640, 480)


def test_the_window_reopens_at_the_remembered_position_on_wayland(qtbot, built) -> None:
    """The same behaviour on the branch `move()` cannot serve.

    What this proves is that the coordinates KWin is handed are the remembered
    ones — through the real clamp, the real script and the real temporary
    file. It cannot prove KWin honours them; nothing in a test suite can, and
    ADR-0007 accepts that. It DOES prove the Wayland branch does not quietly
    fall through to `move()`, which is the defect that looks like working code.
    """
    # Chosen to fit the offscreen platform's 800x800 screen as it stands, so
    # the clamp is not what this test measures — an unfitting rectangle passes
    # through `clamp_to_screens` and arrives somewhere else entirely, which
    # reads as the Wayland branch being wrong. It has its own test above.
    asked: list[Rect] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(100, 200),
        size=(640, 480),
        place=wayland_place(asked),
    )

    assert [(rect.x, rect.y) for rect in asked] == [(100, 200)]
    # The size is Qt's on every platform, so it lands whichever branch ran.
    assert (window.width(), window.height()) == (640, 480)


def test_a_remembered_size_survives_an_empty_project_list(qtbot, built) -> None:
    """`_apply_default_geometry` returns early when there are no rows, so
    without a second application in `_restore_geometry` a user with nothing
    detected gets Qt's default size however they left the window.

    The empty list is the whole point of this test rather than an incidental
    fixture choice — every other test here has two rows, so this is the only
    one in which `_apply_default_geometry` cannot run at all.
    """
    window = geometry_window(qtbot, built, [], position=(50, 60), size=(700, 500))

    assert rows_of(window) == [], "the early-return branch is what this drives"
    assert (window.width(), window.height()) == (700, 500)


def test_a_remembered_size_beats_the_measured_default(qtbot, built) -> None:
    """LWSM-1149 sizes a first run from its content; LWSM-1033 must not undo
    the user's own choice on every later run. Pinned against the default in one
    test so neither half can hold on its own — a window that ignored BOTH
    would pass either assertion alone."""
    chosen = geometry_window(qtbot, built, two_rows(), position=(0, 0), size=(705, 505))
    measured = geometry_window(qtbot, built, two_rows())

    # Two rows, so `_apply_default_geometry` actually runs — it is the half of
    # the mechanism this test exists for, and it returns early with none.
    assert len(rows_of(chosen)) == 2
    assert (chosen.width(), chosen.height()) == (705, 505)
    assert (measured.width(), measured.height()) != (705, 505)


def test_a_maximised_window_reopens_maximised_and_is_not_placed(qtbot, built) -> None:
    """Its position is the screen's, so asking for the stored coordinates would
    un-maximise it to honour them."""
    asked: list[Rect] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(300, 400),
        size=(640, 480),
        maximized=True,
        place=wayland_place(asked),
    )

    assert window.isMaximized()
    assert asked == []


def test_a_position_from_an_unplugged_monitor_lands_on_a_screen(qtbot, built) -> None:
    """The clamp, observed on the window rather than on the arithmetic — a
    `place_window` wired up without `clamp_to_screens` would put the window
    where the user could not reach it."""
    room = QApplication.primaryScreen().availableGeometry()
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(room.x() + room.width() + 4000, 0),
        size=(640, 480),
        place=functools.partial(
            placement.place_window, environ={"XDG_SESSION_TYPE": "x11"}
        ),
    )

    assert window.pos().x() + window.width() <= room.x() + room.width()


def test_nothing_remembered_leaves_the_window_where_it_was_put(qtbot, built) -> None:
    """A first run. `_restore_geometry` must not place a window at (0, 0)
    because that is what an unset coordinate defaults to — which is why
    `Settings` stores `None` rather than `0`."""
    asked: list[Rect] = []
    window = geometry_window(qtbot, built, two_rows(), place=wayland_place(asked))

    assert asked == []
    assert not window.isMaximized()


def test_closing_remembers_the_frame_corner_and_the_client_size(qtbot, built) -> None:
    """The round trip, asserted as a round trip: what `closeEvent` stores is
    exactly what `move` and `resize` were given, so a window reopened from it
    lands where it was rather than a decoration's width away."""
    stored: list[tuple[Rect | None, bool, bool]] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        save_geometry=lambda rect, maximized, known: stored.append(
            (rect, maximized, known)
        ),
    )
    window.resize(720, 540)
    window.move(111, 222)
    qtbot.wait(1)

    window.close()

    assert stored == [(Rect(111, 222, 720, 540), False, True)]


def test_closing_a_maximised_window_remembers_the_flag_and_the_normal_size(
    qtbot, built
) -> None:
    """`normalGeometry`, never `geometry`: storing a maximised window's own
    geometry gives a window that fills the display next run WITHOUT being
    maximised, which the user cannot undo with the maximise button."""
    stored: list[tuple[Rect | None, bool, bool]] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        save_geometry=lambda rect, maximized, known: stored.append(
            (rect, maximized, known)
        ),
    )
    window.resize(720, 540)
    window.move(111, 222)
    qtbot.wait(1)
    window.showMaximized()
    qtbot.wait(1)

    window.close()

    ((rect, maximized, _known),) = stored
    assert maximized
    assert rect is not None
    assert (rect.width, rect.height) == (720, 540)


def test_a_window_with_no_saver_closes_without_complaint(qtbot, built) -> None:
    """The seam defaults to doing nothing for `save_theme`'s reason: closing is
    something a test does by accident, and it must not write into the
    developer's own settings.json."""
    window = geometry_window(qtbot, built, two_rows())

    window.close()

    assert window._save_geometry is None


def test_a_refused_save_is_logged_rather_than_stopping_the_close(qtbot, built) -> None:
    """A window that will not close because its geometry could not be written
    is worse than a window that forgets where it was."""

    def refuse(_rect: Rect | None, _maximized: bool, _known: bool) -> None:
        raise SettingsError("there is no writable configuration directory")

    window = geometry_window(qtbot, built, two_rows(), save_geometry=refuse)

    assert window.close()


def test_centre_on_screen_puts_the_window_in_the_middle(qtbot, built) -> None:
    """The action, observed as a position rather than as a call. Same code path
    as the restore, with the target computed differently — which is ADR-0007's
    observation and the reason there is one `place_window`."""
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(0, 0),
        size=(640, 480),
        place=functools.partial(
            placement.place_window, environ={"XDG_SESSION_TYPE": "x11"}
        ),
    )
    room = QApplication.primaryScreen().availableGeometry()

    window._centre_action.trigger()
    qtbot.wait(1)

    frame = window.frameGeometry()
    assert abs(frame.center().x() - room.center().x()) <= 2
    assert abs(frame.center().y() - room.center().y()) <= 2


def test_centre_on_screen_is_disabled_and_says_why_where_it_cannot_work(
    qtbot, built, monkeypatch
) -> None:
    """ADR-0007's honest degradation: under a Wayland session with no
    `dbus-send` the compositor owns placement and we cannot ask it, so the
    action explains itself rather than being offered and doing nothing."""
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(mainwindow.placement.shutil, "which", lambda _name: None)

    window = geometry_window(qtbot, built, two_rows())

    assert not window._centre_action.isEnabled()
    assert "does not let an application place its own window" in (
        window._centre_action.toolTip()
    )


def test_centre_on_screen_carries_a_mnemonic_and_is_retranslated(qtbot, built) -> None:
    """`§ O8` clause 2 — every action reachable from the keyboard — and the
    label set in `_retranslate_menus` rather than at construction, so
    LanguageChange has one place to go."""
    window = geometry_window(qtbot, built, two_rows())

    assert window._centre_action.text() == "&Centre on screen"
    window._centre_action.setText("")
    window._view_menu.setTitle("")
    window.changeEvent(QEvent(QEvent.Type.LanguageChange))

    assert window._centre_action.text() == "&Centre on screen"
    assert window._view_menu.title() == "&View"


def test_an_enabled_centre_action_explains_nothing_extra(qtbot, built) -> None:
    """The whole point of the disabled one is that it explains itself, so the
    enabled one must not also carry an explanation.

    Asserted as "the tooltip is the label" and not as "there is no tooltip",
    because there is no such state: `setToolTip("")` leaves a `QAction`
    falling back to its own text, the same way `setAccessibleName("")` leaves
    a widget in the accessibility tree. Writing the assertion the other way
    round would fail against correct code.
    """
    window = geometry_window(qtbot, built, two_rows())

    assert window._centre_action.isEnabled()
    assert window._centre_action.toolTip() == "Centre on screen"


def test_centre_reports_when_the_desktop_refuses(qtbot, built) -> None:
    """`place_window` returning `None` is what the user is told about, rather
    than an action that appears to have worked."""
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        place=lambda *_args, **_kwargs: None,
    )

    window.centre_on_screen()

    assert "would not let the window be moved" in window.statusBar().currentMessage()


def test_rows_arriving_after_the_restore_do_not_undo_the_remembered_size(
    qtbot, built
) -> None:
    """The ordering in which `_apply_default_geometry` runs LAST, which is the
    only one where its preference for the remembered size decides anything.

    `_sync_rows` runs inside `__init__`, so a window built with records already
    knows about them and sizes itself before it is ever shown — and
    `_restore_geometry`, which fires off the first `showEvent`, then has the
    last word whatever `_apply_default_geometry` decided. Built with NOTHING,
    the order reverses: the restore happens first and the measured size lands
    afterwards, on top of the size the user chose.

    Found by a mutation that survived the whole suite on 2026-08-21 — every
    other test here reaches this method through the ordering in which its
    result is immediately overwritten, so the branch ran and could not be
    observed. A first run with an empty or unreadable `projects.json` is the
    live case, and a rescan that finds the user's first project is the other.
    """
    controller = build_controller(built, [], FakeProbe(5005))
    window = MainWindow(
        controller, Theme.default(), [], position=(0, 0), size=(705, 505)
    )
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    qtbot.wait(1)
    assert rows_of(window) == [], "the restore must happen before any row exists"

    controller.set_records(two_rows())
    with qtbot.waitSignal(controller.projects_changed, timeout=2000):
        controller.poll_once()
    qtbot.wait(1)

    assert len(rows_of(window)) == 2, "the rows must arrive AFTER the restore"
    assert (window.width(), window.height()) == (705, 505)


def test_a_wayland_session_stores_the_size_and_leaves_the_position_alone(
    qtbot, built, monkeypatch
) -> None:
    """The finding that shaped the whole item, asserted at the seam.

    Under Wayland a client is never told where it is, so Qt answers 0,0 —
    which is a real position, not an error, and would be written as though the
    user had put the window in the corner. Measured against real KWin on
    2026-08-21: the compositor reported this app's window at 640,480 while Qt
    reported 0,0, and 0,0 is what reached `settings.json`.

    Asserted as the FLAG rather than as the absence of coordinates, because
    the window cannot know what is already stored — leaving the existing
    position untouched is `build_window`'s half, and it has its own test. The
    size is stored either way: it is the half Wayland can answer.
    """
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    stored: list[tuple[Rect | None, bool, bool]] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        save_geometry=lambda rect, maximized, known: stored.append(
            (rect, maximized, known)
        ),
    )
    window.resize(660, 470)
    qtbot.wait(1)

    window.close()

    ((rect, _maximized, position_known),) = stored
    assert not position_known, "a Wayland session cannot know where it is"
    assert rect is not None
    assert (rect.width, rect.height) == (660, 470), "the size is still knowable"


def test_a_position_in_the_file_is_still_restored_under_wayland(qtbot, built) -> None:
    """Placement and reading are different problems, and only one of them is
    refused.

    So a position recorded under X11, or typed into the hand-editable file, is
    honoured on a Wayland session even though that session could never have
    written it. Losing that would make the stored coordinates useless to the
    very users ADR-0007's KWin path was built for.
    """
    asked: list[Rect] = []
    geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(100, 200),
        size=(640, 480),
        place=wayland_place(asked),
    )

    assert [(rect.x, rect.y) for rect in asked] == [(100, 200)]


def test_a_window_already_exposed_restores_without_waiting_for_an_expose(
    qtbot, built
) -> None:
    """The fallback branch in `showEvent`, which no ordinary show reaches.

    A window is not exposed while its own `showEvent` is still running, so the
    event filter is what fires in practice. The branch exists because a
    platform that had already presented the surface would otherwise wait for
    an Expose that is never coming again — and the symptom would be a position
    that is silently never restored, which is the whole failure mode ADR-0007
    is about.

    Driven by re-arming the guard on a window that IS exposed, because there
    is no way to ask Qt to deliver the events in the other order. Found by a
    mutation that survived the suite on 2026-08-21.
    """
    asked: list[Rect] = []
    window = geometry_window(
        qtbot,
        built,
        two_rows(),
        position=(60, 70),
        size=(640, 480),
        place=wayland_place(asked),
    )
    assert window.windowHandle().isExposed(), "the fixture must leave it exposed"
    asked.clear()

    window._geometry_restored = False
    window.showEvent(QShowEvent())
    qtbot.wait(1)

    assert [(rect.x, rect.y) for rect in asked] == [(60, 70)]


# --- LWSM-1156: Enter in the filter box jumps to the first remaining row ------
#
# `keyboard_window` and `shown_names` are LWSM-1040's, reused rather than
# rebuilt: three rows wherever a test counts them, and `show=True` only where
# `hasFocus` is asserted, which needs an ACTIVE window. The digit-into-the-box
# case already has a test up there — this item adds a second reason for the
# window and the filter to disagree about a key, not a second copy of it.


def test_enter_in_the_filter_box_focuses_the_first_remaining_row(qtbot, built) -> None:
    """The keystroke the item exists to save (LWSM-1156).

    After `/` and typing, the caret is in the filter box and reaching the
    narrowed list needed a Tab. The app was fully keyboard-operable without
    this — a keystroke saved, not a gap closed, which is why it was out of
    LWSM-1040's filed scope.

    Filtered to the SECOND of three, so a handler that focuses row zero of the
    unfiltered list rather than the first row still showing fails here. That
    distinction is the whole behaviour, and against an unfiltered list the two
    are the same widget.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"], show=True)
    window._filter.setFocus()
    qtbot.waitUntil(window._filter.hasFocus, timeout=2000)

    qtbot.keyClicks(window._filter, "bet")
    qtbot.keyClick(window._filter, Qt.Key.Key_Return)

    assert shown_names(window) == ["beta"], "the filter must have narrowed first"
    focused = [row for row in window._ordered_rows() if row.hasFocus()]
    assert [row._name.text() for row in focused] == ["beta"]


def test_enter_on_a_filter_matching_nothing_does_not_move_focus(qtbot, built) -> None:
    """The edge case the bullet names by name: an empty result set.

    Enter with no remaining rows does nothing and must not move focus or
    raise. Somewhere arbitrary would be worse than leaving the caret where the
    user is typing — a filter matching nothing is the normal state halfway
    through a word.
    """
    window, _ = keyboard_window(qtbot, built, ["alpha", "beta", "gamma"], show=True)
    window._filter.setFocus()
    qtbot.waitUntil(window._filter.hasFocus, timeout=2000)

    qtbot.keyClicks(window._filter, "no-such-project")
    qtbot.keyClick(window._filter, Qt.Key.Key_Return)

    assert shown_names(window) == []
    assert window._filter.hasFocus(), "the caret must stay where the user is typing"


def test_enter_on_a_row_still_clicks_that_row_button(qtbot, built) -> None:
    """The meaning LWSM-1156 must NOT change.

    Two Enters now live in one window: this one clicks the focused row's
    enabled button (LWSM-1040), and the filter box's jumps to the first match.
    Qt's propagation separates them — a `QLineEdit` consumes Return and emits
    `returnPressed`, so the key never reaches a row — and neither handler names
    the other. This is what fails if someone ever "fixes" that with a guard.
    """
    window, controller = keyboard_window(
        qtbot, built, ["alpha", "beta", "gamma"], show=True
    )
    row = window._ordered_rows()[1]
    row.setFocus()
    qtbot.waitUntil(row.hasFocus, timeout=2000)
    started: list[str] = []
    controller.start_project = lambda path: started.append(path.name)

    qtbot.keyClick(row, Qt.Key.Key_Return)

    assert started == ["beta"], "Enter on a row must still drive that row's button"


# --- LWSM-1187: a browser per project -----------------------------------------

BROWSERS = (
    Browser("firefox.desktop", "Firefox", ("/bin/firefox", "%u")),
    Browser("brave.desktop", "Brave", ("/bin/brave", "%u")),
)


def browser_window(qtbot, built, tmp_path, records, saves=None):
    """A writable window whose installed-browser list is injected, not scanned."""
    return rescan_window(
        qtbot,
        built,
        records,
        tmp_path,
        FakeScanResult(projects=()),
        saves=saves,
        browsers_available=BROWSERS,
    )


def with_browser(name: str, port: int | None, entry_id: str | None):
    return dataclasses.replace(record(name, port), browser=entry_id)


def test_the_picker_offers_the_default_and_every_installed_browser(
    qtbot, built, tmp_path
) -> None:
    window, _ = browser_window(qtbot, built, tmp_path, [record("a", 3000)])
    box = row_named(window, "a").browser_box

    assert [box.itemText(i) for i in range(box.count())] == [
        "Default browser",
        "Firefox",
        "Brave",
    ]
    assert box.currentIndex() == 0, "no stored choice must read as the default"


def test_the_picker_shows_the_stored_choice(qtbot, built, tmp_path) -> None:
    window, _ = browser_window(
        qtbot, built, tmp_path, [with_browser("a", 3000, "brave.desktop")]
    )
    assert row_named(window, "a").browser_box.currentText() == "Brave"


def test_a_browser_that_is_no_longer_installed_reads_as_the_default(
    qtbot, built, tmp_path
) -> None:
    """Uninstalling a browser must not lose the choice, or break the row.

    The picker falls back to the default entry rather than growing a phantom
    row for something that cannot be launched — and the stored id STAYS in the
    file, so reinstalling the browser restores the choice. Asserting the record
    is the half that would otherwise rot: a fallback that also cleared the field
    would look identical here.
    """
    window, controller = browser_window(
        qtbot, built, tmp_path, [with_browser("a", 3000, "uninstalled.desktop")]
    )
    assert row_named(window, "a").browser_box.currentIndex() == 0
    assert controller.records()[0].browser == "uninstalled.desktop"


def test_choosing_a_browser_writes_it_to_the_registry(qtbot, built, tmp_path) -> None:
    saves: list = []
    window, controller = browser_window(
        qtbot, built, tmp_path, [record("a", 3000)], saves
    )
    box = row_named(window, "a").browser_box
    box.setCurrentIndex(box.findData("firefox.desktop"))

    assert [r.browser for _path, records, _load in saves for r in records] == [
        "firefox.desktop"
    ]
    assert controller.records()[0].browser == "firefox.desktop"


def test_choosing_the_default_again_stores_none_rather_than_an_empty_string(
    qtbot, built, tmp_path
) -> None:
    """One spelling of "no preference" in the file, so `by_id` has one case."""
    saves: list = []
    window, controller = browser_window(
        qtbot, built, tmp_path, [with_browser("a", 3000, "firefox.desktop")], saves
    )
    row_named(window, "a").browser_box.setCurrentIndex(0)

    assert controller.records()[0].browser is None


def test_rendering_a_changed_choice_does_not_write_it_back(
    qtbot, built, tmp_path
) -> None:
    """The `QSignalBlocker` in `update_from`, which is easy to leave out.

    The view's browser MUST change here. A first draft re-rendered a row whose
    stored choice already matched the box, and the mutation run showed it was
    vacuous: `setCurrentIndex` emits nothing when the index does not move, so
    deleting the blocker left it green. The live case is a rescan or a profile
    import arriving with a different browser — `update_from` then moves the
    index, and without the blocker that fires `currentIndexChanged`, whose
    handler writes projects.json. Rendering must never write.
    """
    saves: list = []
    window, controller = browser_window(
        qtbot, built, tmp_path, [record("a", 3000)], saves
    )
    row = row_named(window, "a")
    assert row.browser_box.currentIndex() == 0, "precondition: no choice yet"
    saves.clear()

    row.update_from(
        dataclasses.replace(controller.rows()[0], browser="firefox.desktop")
    )

    assert row.browser_box.currentText() == "Firefox", "precondition: it moved"
    assert saves == [], f"{len(saves)} registry writes from rendering alone"


def test_open_launches_the_chosen_browser_and_not_the_desktop_default(
    qtbot, built, tmp_path, monkeypatch
) -> None:
    """Driven through `_open_project` rather than the button.

    The button's wiring is pinned by the existing Open tests; what is new here
    is which of the two routes `_open_project` takes, and enabling the button
    needs a bound port and a supervised child this fixture has no reason to
    build.
    """
    launched: list = []
    fell_back: list = []
    monkeypatch.setattr(
        mainwindow.browsers,
        "open_url",
        lambda browser, url: launched.append((browser.entry_id, url)),
    )
    window, controller = browser_window(
        qtbot, built, tmp_path, [with_browser("a", 3000, "brave.desktop")]
    )
    window._open_url = lambda url: fell_back.append(url) or True

    window._open_project(controller.records()[0].path)

    assert launched == [("brave.desktop", "http://localhost:3000/")]
    assert fell_back == [], "the desktop default must not also be consulted"


def test_open_falls_back_to_the_desktop_default_when_nothing_is_chosen(
    qtbot, built, tmp_path, monkeypatch
) -> None:
    launched: list = []
    opened: list = []
    monkeypatch.setattr(
        mainwindow.browsers, "open_url", lambda b, u: launched.append(u)
    )
    window, controller = browser_window(qtbot, built, tmp_path, [record("a", 3000)])
    window._open_url = lambda url: opened.append(url.toString()) or True

    window._open_project(controller.records()[0].path)

    assert opened == ["http://localhost:3000/"]
    assert launched == []


def test_a_browser_that_fails_to_launch_is_reported_not_silent(
    qtbot, built, tmp_path, monkeypatch
) -> None:
    """Silence here looks exactly like a browser that opened behind the window."""

    def boom(browser, url):
        raise mainwindow.browsers.BrowserError("no such binary")

    monkeypatch.setattr(mainwindow.browsers, "open_url", boom)
    window, controller = browser_window(
        qtbot, built, tmp_path, [with_browser("a", 3000, "firefox.desktop")]
    )

    window._open_project(controller.records()[0].path)

    assert "Could not open a browser" in window.statusBar().currentMessage()


# --- LWSM-1174: the name column is capped so the row stays in the lens ---------


def test_a_long_project_name_is_elided_and_keeps_its_full_name(qtbot, built) -> None:
    long_name = "customer-dashboard-frontend-v2"
    window, _ = window_for(qtbot, built, [record(long_name, 5005)], FakeProbe(5005))
    row = rows_of(window)[0]

    assert row._name.text() != long_name, "an uncapped name blows the lens budget"
    assert row._name.text().endswith("…")
    assert long_name.startswith(row._name.text().rstrip("…"))
    assert row._name.toolTip() == long_name, "the whole name must stay reachable"
    assert row.accessibleName() == f"running, {long_name}, port 5005", (
        "a screen reader is read the FULL name — elision is a fitting concern, "
        "and an announcement of a truncated name helps nobody"
    )


def test_every_control_in_the_row_is_named_with_the_FULL_project_name(
    qtbot, built, tmp_path
) -> None:
    """Elision is a fitting concern and must not reach the accessibility tree.

    Found by running the app rather than by a test: every one of these read
    `self._name.text()`, which since LWSM-1174 is the ELIDED string, so a screen
    reader got "Start customer-dash…" — four identical-sounding controls whose
    whole purpose (`§ O8`) is telling one project's buttons from another's. The
    existing tree test could not see it: its fixture's name is short enough that
    elided and full are the same string.
    """
    long_name = "customer-dashboard-frontend-v2"
    window, _ = browser_window(qtbot, built, tmp_path, [record(long_name, 5005)])
    row = rows_of(window)[0]

    assert row._name.text() != long_name, "precondition: the label IS elided"
    assert [
        row.start_button.accessibleName(),
        row.stop_button.accessibleName(),
        row.restart_button.accessibleName(),
        row.open_button.accessibleName(),
        row.browser_box.accessibleName(),
    ] == [
        f"Start {long_name}",
        f"Stop {long_name}",
        f"Restart {long_name}",
        f"Open {long_name} in a browser",
        f"Browser for {long_name}",
    ]


def test_a_short_project_name_is_untouched_and_carries_no_tooltip(qtbot, built) -> None:
    """A tooltip repeating the visible text is noise a magnifier user dismisses.

    This is also the guard on the boundary: `elidedText` is free to cut a string
    whose advance merely EQUALS the width it is handed, and the column is set to
    exactly that advance for every name under the cap. Without the explicit
    fits-check, "alpha" rendered as "alp…".
    """
    window, _ = window_for(qtbot, built, [record("alpha", 5005)], FakeProbe(5005))
    row = rows_of(window)[0]

    assert row._name.text() == "alpha"
    assert row._name.toolTip() == ""


def test_the_row_still_fits_one_lens_view_with_a_browser_picker(
    qtbot, built, tmp_path
) -> None:
    """The band, with the longest name and the picker together (LWSM-1187).

    Measured 2026-08-24: this row was 593 px before the picker existed — 7 px
    inside the limit — and 677 px with an uncapped name column and the picker.
    Capping the name is what bought it back. Both halves are asserted in ONE
    test on purpose: either alone passes against a row that is wrong.
    """
    window, _ = browser_window(
        qtbot, built, tmp_path, [record("customer-dashboard-frontend-v2", 5005)]
    )
    with qtbot.waitExposed(window):
        window.show()
    window.resize(1400, window.height())
    qtbot.waitUntil(lambda: window.width() == 1400, timeout=2000)
    row = rows_of(window)[0]

    assert row.browser_box.isVisible(), "the picker must actually be in the row"
    right_edge = row.open_button.geometry().right()
    assert right_edge <= READABLE_BAND_PX, (
        f"the row's controls end at x={right_edge}, outside the "
        f"{READABLE_BAND_PX} px lens the user has to read it through"
    )
