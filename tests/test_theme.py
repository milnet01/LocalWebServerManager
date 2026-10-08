"""LWSM-1005 INV-17 — `docs/standards/testing-overrides.md § T8` contrast arithmetic.

Computed over every palette rather than eyeballed, so adding one that fails is
a failing build rather than a discovery months later. LWSM-1031 landed the six
adopted palettes plus high-contrast in light and dark, and this file is where
its acceptance criterion is met: **every** theme, **every** text token,
**every** surface it can land on.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

# tests/ has no __init__.py, so pytest puts it on sys.path itself and this is a
# flat import rather than `tests.contrast`.
from contrast import (
    HIGH_CONTRAST_FLOOR,
    INDICATOR_FLOOR,
    STATE_SEPARATION,
    TEXT_FLOOR,
    contrast_ratio,
    delta_e2000,
    relative_luminance,
)
from lwsm.controller import ProjectStatus
from lwsm.theme import (
    DEFAULT_THEME,
    FOLLOW_SYSTEM,
    OutlineStyle,
    Theme,
    install_outline_style,
    resolve_theme_id,
    theme_for_id,
)
from lwsm.theme import THEMES as PALETTES

# Derived from the registry, never listed: a palette added to `theme.py` and
# forgotten here would be a theme with no contrast test at all, which is the
# one failure § T8's "adding a theme that fails is a failing build" forbids.
THEMES = [pytest.param(theme, id=name) for name, theme in PALETTES.items()]


def floor_for(theme: Theme) -> float:
    return HIGH_CONTRAST_FLOOR if theme.high_contrast else TEXT_FLOOR


# --- the arithmetic itself, before anything is asserted with it ---------------


def test_the_contrast_formula_matches_published_values() -> None:
    """Guards the instrument.

    A miscomputed ratio would pass every palette silently, which is
    indistinguishable from a clean one — the same trap `test_layering.py`'s
    can-actually-fail test exists for.
    """
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)
    # #767676 on white is WCAG's canonical borderline: the lightest grey that
    # still clears 4.5:1, and #777777 is the shade that just misses.
    assert contrast_ratio("#767676", "#ffffff") == pytest.approx(4.54, abs=0.02)
    assert contrast_ratio("#777777", "#ffffff") < TEXT_FLOOR
    # Order must not matter — the formula sorts by luminance, not by argument.
    assert contrast_ratio("#1a7f3c", "#f4f4f6") == contrast_ratio("#f4f4f6", "#1a7f3c")
    assert relative_luminance("#fff") == relative_luminance("#ffffff")
    # Saturated, mid-luminance pairs. The greys above exercise one channel
    # weighting only; the derivation script shares this function, so an error
    # in the weights would agree with itself everywhere else (LWSM-1278).
    assert contrast_ratio("#0000ff", "#ffffff") == pytest.approx(8.59, abs=0.01)
    assert contrast_ratio("#ff0000", "#ffffff") == pytest.approx(4.00, abs=0.01)
    assert contrast_ratio("#008000", "#ffffff") == pytest.approx(5.14, abs=0.01)


# --- LWSM-1070: the focus ring has to be seen to be a focus ring --------------


@pytest.mark.parametrize("surface", ["window", "base", "alt_base"])
@pytest.mark.parametrize("theme", THEMES)
def test_the_focus_ring_clears_the_indicator_floor(theme: Theme, surface: str) -> None:
    # Every surface, not only `window`: ledger's accent was 2.85:1 on
    # `alt_base` until LWSM-1207, and nothing here would have noticed (LWSM-1278).
    ratio = contrast_ratio(theme.accent, getattr(theme, surface))
    assert ratio >= INDICATOR_FLOOR, (
        f"the focus ring is {ratio:.2f}:1 against {surface}, below § T8's "
        f"{INDICATOR_FLOOR}:1 for a non-text indicator"
    )


class _Ring(NamedTuple):
    ring: str  # the colour drawn at the control's edge once focused
    inside: str  # the control's own fill just inside the ring
    width: int  # how many pixels in from the edge the focus change runs
    row_width: int  # what `ProjectRow.focus_ring_width` gives this font


def _hexed(pixel: int) -> str:
    return f"#{pixel & 0xFFFFFF:06x}"


# Every kind of focusable control the app builds: the row's buttons, the
# filter box, the browser picker, the settings dialog's port fields and
# folder list, and the first-run dialog's check boxes (review-code 2026-10-08
# L09-H1). The row paints its own ring and has its own tests in
# `test_mainwindow.py` (LWSM-1292).
FOCUSABLE = ["button", "line_edit", "combo_box", "spin_box", "list", "check_box"]


def _control(kind: str) -> QWidget:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QFrame,
        QLineEdit,
        QListWidget,
        QPushButton,
        QSpinBox,
    )

    if kind == "button":
        return QPushButton("Start")
    if kind == "line_edit":
        # Empty, as the filter box opens: tabbing into a line edit selects
        # its text, and the "inside" sample would then be the selection.
        return QLineEdit()
    if kind == "combo_box":
        box = QComboBox()
        box.addItems(["Firefox", "Chromium"])
        return box
    if kind == "spin_box":
        return QSpinBox()
    if kind == "check_box":
        # Ticked, as the first-run dialog opens: Fusion drew a ticked box as a
        # bare tick on the dark palettes, with no outline at all (rendered on
        # midnight, 2026-10-08).
        box = QCheckBox("alpha")
        box.setChecked(True)
        return box
    if kind == "list":
        # Empty, so the inside sample is the list's own fill, not an item.
        listing = QListWidget()
        listing.setFixedHeight(60)
        return listing
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setMinimumSize(60, 30)
    return frame


def _outline_point(target: QWidget) -> tuple[int, int]:
    """Where a control's outline is: its left edge at mid-height, except a
    check box, whose outline is on its indicator rather than its edge."""
    from PySide6.QtWidgets import QCheckBox, QStyle, QStyleOptionButton

    if isinstance(target, QCheckBox):
        # Where `OutlineStyle` has Fusion draw it: inside the inset rect.
        option = QStyleOptionButton()
        option.initFrom(target)
        inset = OutlineStyle.check_box_inset(target.fontMetrics())
        option.rect = option.rect.adjusted(inset, inset, -inset, -inset)
        indicator = target.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, target
        )
        return indicator.left(), indicator.center().y()
    return 0, target.height() // 2


def _rendered_ring(
    qtbot, theme: Theme, kind: str = "button", scale: int = 100
) -> _Ring:
    """The ring the app DRAWS on a keyboard-focused control, and its inside fill.

    `kind` is one of `FOCUSABLE`.

    Real widgets, the application style, palette and font, the window style
    sheet, and focus moved by a real Backtab: Qt draws a focus ring only when
    `WA_KeyboardFocusChange` is set, which `setFocus` alone never sets
    (CLAUDE.md's `QStyleOption` trap). The ring is the pixels that change
    when focus arrives, sampled at mid-height on the left edge.

    `scale` multiplies the application font as the text-size control does,
    because the ring's width is promised to follow it (LWSM-1349).
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

    app = QApplication.instance()
    install_outline_style(app)
    previous, previous_font = app.palette(), app.font()
    app.setPalette(theme.to_palette())
    font = app.font()
    font.setPointSizeF(font.pointSizeF() * scale / 100)
    app.setFont(font)
    try:
        window = QWidget()
        qtbot.addWidget(window)
        window.setStyleSheet(theme.style_sheet())
        layout = QHBoxLayout(window)
        target = _control(kind)
        other = QPushButton("Stop")
        layout.addWidget(target)
        layout.addWidget(other)
        with qtbot.waitExposed(window):
            window.show()
        with qtbot.waitActive(window):
            window.activateWindow()
        other.setFocus()
        plain = target.grab().toImage()
        qtbot.keyClick(other, Qt.Key.Key_Backtab)
        assert target.hasFocus()
        focused = target.grab().toImage()
        # The row's own formula, on this control's font: the user chose one
        # ring width for every focusable thing (LWSM-1349, 2026-10-01).
        row_width = max(1, round(target.fontMetrics().height() / 8))
    finally:
        app.setPalette(previous)
        app.setFont(previous_font)
    row = focused.height() // 2
    changed = [
        x
        for x in range(focused.width())
        if focused.pixel(x, row) != plain.pixel(x, row)
    ]
    assert changed, "no focus ring was drawn at all"
    # A ring sits at the control's own edge. A focused line edit also shows a
    # text cursor a few pixels in, and with the ring gone that cursor is the
    # only change, which contrasts well and would pass for one (measured).
    assert changed[0] <= 1, (
        f"the first change is at x={changed[0]}, inside the control: that is "
        f"not a ring around it"
    )
    edge = changed[0]
    while edge + 1 in changed:
        edge += 1

    return _Ring(
        ring=_hexed(focused.pixel(changed[0], row)),
        inside=_hexed(focused.pixel(edge + 3, row)),
        width=edge - changed[0] + 1,
        row_width=row_width,
    )


@pytest.mark.gui
@pytest.mark.parametrize("kind", FOCUSABLE)
@pytest.mark.parametrize("theme", THEMES)
def test_the_ring_fusion_draws_clears_the_indicator_floor(
    qtbot, theme: Theme, kind: str
) -> None:
    """LWSM-1238. The test above holds the accent TOKEN against the window, and
    that is not what reaches the screen: Fusion draws a button's ring in a
    darkened accent. Graphite's token cleared 3:1 while its drawn ring was
    2.26:1 against the button and 2.75:1 against the window.

    Held against both neighbours of the ring, the control's own fill inside it
    and the window outside it (WCAG 1.4.11's adjacent colours).
    """
    drawn = _rendered_ring(qtbot, theme, kind)

    for name, neighbour in (
        ("its own fill", drawn.inside),
        ("the window", theme.window),
    ):
        ratio = contrast_ratio(drawn.ring, neighbour)
        assert ratio >= INDICATOR_FLOOR, (
            f"the drawn focus ring {drawn.ring} is {ratio:.2f}:1 against {name} "
            f"{neighbour}, below § T8's {INDICATOR_FLOOR}:1"
        )


@pytest.mark.gui
@pytest.mark.parametrize("scale", [100, 200])
@pytest.mark.parametrize("kind", FOCUSABLE)
@pytest.mark.parametrize("theme", THEMES)
def test_every_focus_ring_is_as_thick_as_the_rows(
    qtbot, theme: Theme, kind: str, scale: int
) -> None:
    """LWSM-1349. `design-accessibility.md` promises a THICK ring on every
    focusable control, and Fusion drew 1 px on a button and a combo box and
    2 px on a line edit, the same at every text size. The user chose the
    row's width for all of them (2026-10-01), which grows with the text.

    At 200 % as well as 100 %: Fusion's line edit already met the 100 %
    width, so only the larger size can tell a ring that follows the text
    from one that happens to match it once.
    """
    drawn = _rendered_ring(qtbot, theme, kind, scale)

    assert drawn.width >= drawn.row_width, (
        f"the focus ring is {drawn.width} px at {scale} % text, thinner than "
        f"the row's {drawn.row_width} px"
    )


@pytest.mark.parametrize("surface", ["window", "base", "alt_base"])
@pytest.mark.parametrize("theme", THEMES)
def test_every_outline_clears_the_indicator_floor(theme: Theme, surface: str) -> None:
    """LWSM-1337. The `border` token outlines rows and fields, and nothing
    held it to anything: 1.19-1.42:1 on every surface of the six ordinary
    palettes, so the outline was there and could not be seen. An outline is
    a non-text indicator, so it takes § T8's 3:1 (the user, 2026-10-01).
    """
    ratio = contrast_ratio(theme.border, getattr(theme, surface))
    assert ratio >= INDICATOR_FLOOR, (
        f"the outline {theme.border} is {ratio:.2f}:1 against {surface}, "
        f"below § T8's {INDICATOR_FLOOR}:1 for a non-text indicator"
    )


@pytest.mark.gui
@pytest.mark.parametrize("kind", [*FOCUSABLE, "frame"])
@pytest.mark.parametrize("theme", THEMES)
def test_the_outline_on_screen_is_the_border_token(
    qtbot, theme: Theme, kind: str
) -> None:
    """LWSM-1337. The token clearing 3:1 changes nothing unless it is what
    gets drawn: Fusion outlines a control in a shade it derives from the
    window colour, so high-contrast dark showed near-invisible outlines
    while its `border` token was white (docs/screenshots/high-contrast.png).

    Read at the control's left edge, mid-height, unfocused. `frame` is the
    project row's shape, a `QFrame` with a styled panel.
    """
    from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

    app = QApplication.instance()
    install_outline_style(app)
    previous = app.palette()
    app.setPalette(theme.to_palette())
    try:
        window = QWidget()
        qtbot.addWidget(window)
        window.setStyleSheet(theme.style_sheet())
        layout = QHBoxLayout(window)
        target = _control(kind)
        layout.addWidget(target)
        with qtbot.waitExposed(window):
            window.show()
        image = target.grab().toImage()
        x, y = _outline_point(target)
    finally:
        app.setPalette(previous)

    edge = _hexed(image.pixel(x, y))
    assert edge == theme.border, (
        f"the {kind}'s outline is drawn in {edge}, not the border token {theme.border}"
    )


# --- LWSM-1075: every token that renders as TEXT clears the text floor --------

# The state tokens colour the state *word*, not just the glyph, so they are
# text pairs and take § T8's 4.5:1 rather than the 3:1 an indicator gets.
TEXT_TOKENS = [
    "text",
    "muted_text",
    "attention",
    "state_running",
    "state_starting",
    "state_wrong_port",
    "state_foreign",
    "state_blocked",
    "state_failed",
    "state_stopped",
    "state_unknown",
]

# `window` is not the only background a token lands on. `base` and `alt_base`
# are what LWSM-1007's list view, P05's inputs and any alternating row will
# paint under — no widget paints `alt_base` today, and it is held to the floor
# anyway, because the day one does is not the day to discover the pair fails.
SURFACES = ["window", "base", "alt_base"]


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("token", TEXT_TOKENS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_text_token_clears_the_text_floor(
    theme: Theme, token: str, surface: str
) -> None:
    """The whole of LWSM-1031's acceptance criterion, and it is parametrised
    three ways on purpose: a theme, a token or a surface added to any one of
    the lists above is covered without anyone remembering to cover it."""
    floor = floor_for(theme)
    ratio = contrast_ratio(getattr(theme, token), getattr(theme, surface))
    assert ratio >= floor, (
        f"{token} is {ratio:.2f}:1 against {surface}, below § T8's "
        f"{floor}:1 for a text pair on this palette"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_selected_text_clears_the_text_floor(theme: Theme) -> None:
    """Qt paints selected text as `HighlightedText` on `Highlight`.

    `palette()` binds those to `base` on `accent`, so the pair is LIVE text —
    every selection in the filter box and in any editable field — and nothing
    looked at it. `derive_state_tokens.py` checks `accent` against `window`
    only, against the INDICATOR floor, so neither the tool nor its shortfall
    report could see this (LWSM-1207).

    Measured before the fix: ledger 3.37:1, mint 3.49:1, parchment 3.73:1 and
    graphite 4.18:1, against the 4.5:1 that `design-accessibility.md` and
    `testing-overrides.md § T8` both require of a text pair.

    Asserted from the PALETTE's own two roles rather than from the token
    names, so re-binding either role to a different token keeps this honest.
    """
    floor = floor_for(theme)
    ratio = contrast_ratio(theme.base, theme.accent)
    assert ratio >= floor, (
        f"selected text is {ratio:.2f}:1 (HighlightedText on Highlight), "
        f"below § T8's {floor}:1 for a text pair on this palette"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_the_accent_still_carries_a_hue(theme: Theme) -> None:
    """The state-token trap, one token along, and a mutant found it.

    LWSM-1207 darkened four accents until the selected-text pair cleared the
    floor. Solving for contrast alone converges on black or white — that is
    what the first state-token solver did — and an accent with no hue is a
    focus ring that identifies nothing while passing every ratio above.
    Replacing ledger's accent with pure black survived the whole suite.

    Held on saturation rather than on a ratio, because that is the property
    contrast cannot express.
    """
    import colorsys

    value = theme.accent.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    _hue, _lightness, saturation = colorsys.rgb_to_hls(red, green, blue)

    assert saturation > 0.1, (
        f"the accent {theme.accent} is {saturation:.2f} saturated — a grey "
        "accent clears every contrast floor and identifies nothing"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_the_state_tokens_are_distinguishable_from_the_body_text(
    theme: Theme,
) -> None:
    """A state token that has collapsed onto `text` carries no state.

    Clearing the contrast floor does not make a token *mean* anything: solving
    every hue for legibility alone converges on near-white over a dark palette,
    which is exactly the mistake the first draft of the solver made and passed
    every check above. Held to a real separation from `text`, in RGB rather
    than in contrast, since two colours can share a luminance and differ.
    """
    for token in (t for t in TEXT_TOKENS if t.startswith("state_")):
        value = getattr(theme, token)
        assert value != theme.text, f"{token} is the body text colour"


@pytest.mark.parametrize("theme", THEMES)
def test_every_pair_of_state_tokens_is_clearly_different(theme: Theme) -> None:
    """LWSM-1338: the solver stops each token at the first lightness clearing
    the floor, so they all shared one luminance and differed by hue alone;
    `wrong_port` and `unknown` were 6 to 10 CIEDE2000 apart. All seven states
    can sit in one list now (LWSM-1011), so every pair is held apart."""
    import itertools

    tokens = [t for t in TEXT_TOKENS if t.startswith("state_")]
    close = [
        (
            first,
            second,
            round(delta_e2000(getattr(theme, first), getattr(theme, second)), 1),
        )
        for first, second in itertools.combinations(tokens, 2)
        if delta_e2000(getattr(theme, first), getattr(theme, second)) < STATE_SEPARATION
    ]
    assert close == [], close


# --- LWSM-1031: the registry itself, and LWSM-1147's default -----------------


def test_the_default_theme_is_dark() -> None:
    """LWSM-1147, and the reason it is a separate item: LWSM-1031 resolves
    follow-system to midnight or ledger, and follow-system on a light desktop
    opens light. Asserted on `is_dark` as well as on the id, so renaming the
    palette cannot quietly turn the app light."""
    assert DEFAULT_THEME == "midnight"
    assert Theme.default() is PALETTES[DEFAULT_THEME]
    assert Theme.default().is_dark


def test_the_registry_holds_six_themes_plus_high_contrast_in_both() -> None:
    """The count LWSM-1031 filed, and the light/dark split `is_dark` drives in
    the picker. `high_contrast` is asserted to agree with the ids rather than
    trusted, because the flag is what selects the 7:1 floor above — a palette
    flagged by mistake would be held to a floor it never had to meet."""
    ordinary = [name for name in PALETTES if not name.startswith("highcontrast")]
    assistive = [name for name in PALETTES if name.startswith("highcontrast")]
    # The ids by name, not merely the count: LWSM-1031 names these six as
    # adopted from finbreak, and settings.json stores the id, so renaming one
    # silently drops a user's stored choice back to the default. A count alone
    # cannot see that — verified, a mutant renaming `parchment` survived it.
    assert ordinary == [
        "ledger",
        "parchment",
        "mint",
        "midnight",
        "graphite",
        "emerald",
    ]
    assert len(ordinary) == 6
    assert sorted(assistive) == ["highcontrast-dark", "highcontrast-light"]
    assert sum(not PALETTES[name].is_dark for name in ordinary) == 3
    for name, theme in PALETTES.items():
        assert theme.high_contrast == name.startswith("highcontrast"), name
        assert theme.label, name


def test_an_unknown_theme_id_falls_back_rather_than_raising() -> None:
    """settings.json is hand-editable and a theme can be removed by an upgrade
    the user did not read the notes for. A `KeyError` here is a window that
    does not open, so the id resolves to the default instead."""
    assert theme_for_id("no-such-theme") is Theme.default()
    assert theme_for_id("") is Theme.default()
    assert theme_for_id("emerald") is PALETTES["emerald"]


@pytest.mark.parametrize("theme", THEMES)
def test_each_state_takes_its_own_token_and_stopping_takes_none(
    theme: Theme,
) -> None:
    """The mapping, asserted per state rather than through the style sheet.

    `test_the_style_sheet_carries_every_state` cannot see this: with a state
    unmapped, `state_token` returns `text`, `text` is in the sheet under some
    other rule, and the membership assertion holds anyway. A mutant deleting
    the STARTING row survived that test and dies on this one.

    STOPPING is asserted to have NO token of its own, because `design-look-and-feel.md §
    Tokens, not colours` gives it none — it is the optimistic overlay's transient label
    rather than a state derived from observation, and a token appearing for it later is
    a design change, not a fix.
    """
    assert theme.state_token(ProjectStatus.RUNNING) == theme.state_running
    assert theme.state_token(ProjectStatus.STARTING) == theme.state_starting
    assert theme.state_token(ProjectStatus.STOPPED) == theme.state_stopped
    assert theme.state_token(ProjectStatus.UNKNOWN) == theme.state_unknown
    assert theme.state_token(ProjectStatus.STOPPING) == theme.text


# --- LWSM-1077: the theme owes a style sheet, not just a palette --------------


@pytest.mark.parametrize("theme", THEMES)
def test_the_style_sheet_carries_every_state(theme: Theme) -> None:
    """`design-look-and-feel.md § Tokens, not colours` gives a Theme two
    outputs. Only the palette existed, so widget code composed the CSS itself."""
    sheet = theme.style_sheet()

    for status in ProjectStatus:
        assert theme.state_token(status) in sheet, f"{status} has no rule"
        assert f'{Theme.STATE_PROPERTY}="{status.value}"' in sheet


@pytest.mark.parametrize("theme", THEMES)
def test_every_palette_role_carries_its_token(theme: Theme) -> None:
    """Button, ButtonText, HighlightedText and the tooltip roles were left at
    the style default, so P05's buttons would not have followed the theme.

    Asserted against the token's value, not against `isValid()` — an unset role
    is a valid colour too, so that check passes for exactly the defect it would
    be written to catch.
    """
    from PySide6.QtGui import QColor, QPalette

    palette = theme.to_palette()
    expected = {
        QPalette.ColorRole.Window: theme.window,
        QPalette.ColorRole.Base: theme.base,
        QPalette.ColorRole.AlternateBase: theme.alt_base,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.PlaceholderText: theme.muted_text,
        QPalette.ColorRole.Highlight: theme.accent,
        QPalette.ColorRole.Mid: theme.border,
        QPalette.ColorRole.Button: theme.window,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.HighlightedText: theme.base,
        QPalette.ColorRole.ToolTipBase: theme.base,
        QPalette.ColorRole.ToolTipText: theme.text,
    }
    for role, token in expected.items():
        assert palette.color(role) == QColor(token), role


# --- LWSM-1244: follow-system, the id that names a rule and not a palette -----


def test_follow_system_is_deliberately_not_a_palette() -> None:
    """The picker, the contrast floor tests and the light/dark grouping all
    iterate `THEMES`. Were the rule an entry there, every one of them would
    need to special-case it — and one that forgot would hold a rule to a
    contrast floor it has no colours to meet."""
    assert FOLLOW_SYSTEM not in PALETTES


@pytest.mark.parametrize(
    ("dark", "high_contrast", "expected"),
    [
        (False, False, "ledger"),
        (True, False, "midnight"),
        (False, True, "highcontrast-light"),
        (True, True, "highcontrast-dark"),
    ],
)
def test_follow_system_resolves_to_the_four_documented_targets(
    dark: bool, high_contrast: bool, expected: str
) -> None:
    """`design-look-and-feel.md § Themes` names these four. All four are
    asserted rather than one per flag: the two inputs are independent, so a
    mapping that read only one of them would still pass a test that varied
    only the other."""
    resolved = resolve_theme_id(FOLLOW_SYSTEM, dark=dark, high_contrast=high_contrast)
    assert resolved == expected
    assert PALETTES[resolved].is_dark is dark
    assert PALETTES[resolved].high_contrast is high_contrast


def test_a_desktop_that_says_nothing_gets_the_documented_dark_default() -> None:
    """Qt answers `Unknown` wherever no platform theme is loaded, which is
    every test in this suite and any session with no portal. Not knowing must
    land on the same palette a first run gets, or the app would open light for
    a user who never chose light."""
    assert (
        resolve_theme_id(FOLLOW_SYSTEM, dark=None, high_contrast=False) == DEFAULT_THEME
    )
    assert (
        resolve_theme_id(FOLLOW_SYSTEM, dark=None, high_contrast=True)
        == "highcontrast-dark"
    )


@pytest.mark.parametrize("theme_id", [*PALETTES, "a-theme-that-was-removed"])
def test_every_other_id_passes_through_untouched(theme_id: str) -> None:
    """A user who picked Midnight asked for dark and keeps it on a light
    desktop. Asserted over every shipped id AND an unknown one, because this
    function resolves a rule and deliberately does not validate a palette
    name — that is `theme_for_id`'s job, kept in one place."""
    for dark in (True, False, None):
        for high_contrast in (True, False):
            assert (
                resolve_theme_id(theme_id, dark=dark, high_contrast=high_contrast)
                == theme_id
            )


def test_an_unresolved_follow_system_falls_back_to_dark_rather_than_raising() -> None:
    """`follow-system` is absent from `THEMES`, so a caller that skipped the
    resolve reaches `theme_for_id` with it. A `KeyError` there is a window that
    does not open; the default is the one outcome that is certainly usable."""
    assert theme_for_id(FOLLOW_SYSTEM) is PALETTES[DEFAULT_THEME]


# --- LWSM-1298: a pressed control confirms the click --------------------------


@pytest.mark.parametrize("theme", THEMES)
def test_the_style_sheet_gives_a_pressed_button_its_own_colours(theme: Theme) -> None:
    """A click that shows nothing is a click the user cannot tell landed.

    Reported 2026-09-06. Pressed rendering was entirely the platform style's,
    held to none of the floors the palettes are built against.

    **Pressed is not a general rule about platform states, and LWSM-1300 is
    the counter-example twice over.** A `:disabled` rule written by analogy with
    this one made the two states harder to tell apart, because disabled dimming
    belongs to the palette and a style-sheet rule overrides it. That the theme
    was suppressing the dimming altogether is a separate fault, fixed in
    `to_palette`. Measure the state you are about to style; do not reason from
    this test.

    **This docstring twice said something false and both halves are corrected
    here.** It called the platform's pressed rendering "strong under Fusion
    (2175 of 2400 pixels change)"; measured as contrast that same rendering is
    1.08:1 on `midnight` — invisible, every pixel having moved by a couple of
    RGB units. A changed-pixel count is not visibility. And it named "the
    reporter's Breeze desktop": PySide6 ships its own Qt, so the system Breeze
    plugin cannot bind to it and this app resolves to Fusion.
    """
    sheet = theme.style_sheet()

    assert "QPushButton:pressed" in sheet, "no theme confirms a press"
    assert theme.accent in sheet


@pytest.mark.parametrize("theme", THEMES)
def test_a_pressed_button_label_stays_readable(theme: Theme) -> None:
    """The pressed pair is a text pair, so it owes § T8's text floor.

    Asserted by recomputing rather than by trusting the choice, and read OUT
    OF THE SHEET rather than off the palette. A mutant swapping the pressed
    text to `text` survived the palette-only form: that asserted a property
    of two tokens and never that the rule uses them, which is the
    mechanism-not-the-wiring shape recorded throughout `CLAUDE.md`.
    """
    rule = next(
        line
        for line in theme.style_sheet().splitlines()
        if "QPushButton:pressed" in line
    )
    background = re.search(r"background-color:\s*(#[0-9a-fA-F]{6})", rule)
    foreground = re.search(r"[^-]color:\s*(#[0-9a-fA-F]{6})", rule)
    assert background and foreground, rule
    assert contrast_ratio(foreground.group(1), background.group(1)) >= floor_for(theme)


# --- LWSM-1247: one default, in one place ------------------------------------


def test_the_default_theme_id_is_written_once() -> None:
    """`settings.DEFAULT_THEME` and `theme.DEFAULT_THEME` were two literals.

    Both read `"midnight"`, in two files, with nothing tying them — while
    `CLAUDE.md` records the aliasing pattern existing *precisely* so "the
    file's default and the code's default cannot drift". The rule was stated
    for `POLL_INTERVAL_MS` and `MAX_LOG_BYTES` and not applied here.

    `settings.py` is core and may not import `theme.py` (`§ O1`), so the alias
    goes the other way: the UI layer names the core module's value.

    **Asserted against the SOURCE, because the obvious runtime check cannot
    fail.** `theme.DEFAULT_THEME is settings.DEFAULT_THEME` passes with two
    independent literals, since CPython interns a short string constant — so
    that assertion measures interning and reports it as aliasing. Read the
    import instead, the way `test_layering.py` reads source for the rules a
    runtime check cannot see.
    """
    from lwsm import settings, theme

    assert theme.DEFAULT_THEME == settings.DEFAULT_THEME

    source = Path(theme.__file__).read_text(encoding="utf-8")
    assert "DEFAULT_THEME" in source
    assert re.search(r"^DEFAULT_THEME\s*=\s*[\"']", source, re.MULTILINE) is None, (
        "theme.py defines its own DEFAULT_THEME literal beside settings.py's"
    )
    takes_it_from_settings = re.search(
        r"^from lwsm\.settings import .*DEFAULT_THEME", source, re.MULTILINE
    )
    assert takes_it_from_settings, (
        "theme.py does not take the default from the module that owns it"
    )


def test_the_stored_default_names_a_theme_that_exists() -> None:
    """The property a user actually feels, asserted end to end.

    This is what a drift between the two literals would have broken: a fresh
    `Settings()` carries the id, `theme_for_id` resolves it, and a mismatch
    would silently return the fallback — which is the same silent shape
    LWSM-1245 found in the documents.
    """
    from lwsm.settings import Settings

    assert Settings().theme in PALETTES
    assert theme_for_id(Settings().theme) is PALETTES[DEFAULT_THEME]


# --- LWSM-1300: a disabled control has to LOOK disabled -----------------------

# Enabled and disabled labels must be this far apart as a contrast ratio. A
# themed palette produced 1.00 — identical — in every one of the palettes.
DISABLED_LABEL_DELTA = 2.0
# And the disabled label must sit at or under this share of the enabled label's
# contrast against its own fill, so "dimmer" is a drop rather than a nudge.
DISABLED_CONTRAST_SHARE = 0.5


# How far in from the edge the fill and label are read. The outline is drawn
# in ONE colour round the whole perimeter while Fusion shades a button's fill
# across many, so read over the whole widget the outline out-counted every
# fill shade and was taken for the fill (LWSM-1337, measured 2026-10-01).
_EDGE_BAND = 3


def _fill_and_label(widget: QWidget) -> tuple[str, str, str]:
    """A rendered control's own fill, the colour furthest from it (its label),
    and its outline: the pixel at its left edge, mid-height.

    Read off a REAL widget in a REAL state. `CLAUDE.md` records why: a hand-built
    `QStyleOption` with `State_Enabled` cleared does not reproduce the disabled
    path, and reading one produced both this item's wrong filing and its wrong
    closure. Contrast, never a changed-pixel count, for the same reason.
    """
    image = widget.grab().toImage()
    edge = image.pixelColor(0, image.height() // 2).name()
    seen: dict[str, int] = {}
    for y in range(_EDGE_BAND, image.height() - _EDGE_BAND):
        for x in range(_EDGE_BAND, image.width() - _EDGE_BAND):
            name = image.pixelColor(x, y).name()
            seen[name] = seen.get(name, 0) + 1
    fill = max(seen, key=lambda name: seen[name])
    return fill, max(seen, key=lambda name: contrast_ratio(name, fill)), edge


# Three roles carry disabled text and each reaches a different control: a
# button's label, a menu entry or plain label, and a text field. Covered
# separately because setting one and not the others is a mutation that survives.
WIDGETS = ["button", "label", "field"]


@pytest.mark.gui
@pytest.mark.parametrize("kind", WIDGETS)
@pytest.mark.parametrize("theme", THEMES)
def test_a_disabled_control_looks_disabled(
    theme: Theme, kind: str, qtbot, qapp
) -> None:
    """Enablement the user cannot see is enablement that reads as broken.

    `_apply_button_state` has always disabled the controls a state does not
    offer. Reported 2026-09-06 as buttons that all look alike, with a screenshot
    of two running projects whose Start looked as live as their neighbours'.

    The palette is the layer, not the style sheet. `to_palette` writes every
    token through the two-argument `setColor`, which fills Active, Inactive AND
    Disabled with one colour — so a theme overwrote the platform's dimming with
    full-strength text. A `:disabled` style-sheet rule was tried first and
    backed out: `muted_text` is tuned to stay readable, so it came out brighter
    than what it replaced.

    Both halves are asserted because neither implies the other: two labels can
    differ while both stay bright, and a dim label proves nothing if the enabled
    one is dim too.
    """
    from PySide6.QtWidgets import (
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    makers = {
        "button": lambda parent: QPushButton("Start", parent),
        "label": lambda parent: QLabel("Centre on screen", parent),
        "field": lambda parent: QLineEdit("Filter", parent),
    }
    make = makers[kind]
    # The app's style, so this reads what the app draws whatever ran first.
    install_outline_style(qapp)
    original = qapp.palette()
    try:
        qapp.setPalette(theme.to_palette())
        holder = QWidget()
        qtbot.addWidget(holder)
        holder.setStyleSheet(theme.style_sheet())
        layout = QVBoxLayout(holder)
        enabled = make(holder)
        disabled = make(holder)
        layout.addWidget(enabled)
        layout.addWidget(disabled)
        disabled.setEnabled(False)
        holder.resize(200, 80)
        holder.show()
        qapp.processEvents()
        on_fill, on_label, on_edge = _fill_and_label(enabled)
        off_fill, off_label, off_edge = _fill_and_label(disabled)
    finally:
        qapp.setPalette(original)

    # The outline dims with the label (LWSM-1337): at full strength round a
    # dimmed label it made a disabled button read as live again. A label has
    # no outline, so only the outlined kinds are held to this.
    if kind != "label":
        assert contrast_ratio(off_edge, theme.window) < contrast_ratio(
            on_edge, theme.window
        ), f"disabled outline {off_edge} is as strong as enabled {on_edge}"

    assert contrast_ratio(on_label, off_label) >= DISABLED_LABEL_DELTA, (
        f"disabled label {off_label} against enabled {on_label}"
    )
    on_contrast = contrast_ratio(on_label, on_fill)
    off_contrast = contrast_ratio(off_label, off_fill)
    assert off_contrast <= on_contrast * DISABLED_CONTRAST_SHARE, (
        f"disabled {off_contrast:.2f}:1 against enabled {on_contrast:.2f}:1"
    )


def test_an_unknown_theme_id_is_logged_and_follow_system_is_not(caplog) -> None:
    """LWSM-1278: the fallback was silent, so a palette the user chose that a
    later build removed simply never appeared, with nothing in the log saying
    why. `FOLLOW_SYSTEM` reaches the same fallback by design and is not noise.
    """
    with caplog.at_level(logging.WARNING, logger="lwsm.theme"):
        theme_for_id("no-such-theme")
    assert "no-such-theme" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="lwsm.theme"):
        theme_for_id(FOLLOW_SYSTEM)
        theme_for_id(DEFAULT_THEME)
    assert not caplog.records, caplog.text
