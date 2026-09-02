"""LWSM-1005 INV-17 — `docs/standards/testing.md § T8` contrast arithmetic.

Computed over every palette rather than eyeballed, so adding one that fails is
a failing build rather than a discovery months later. LWSM-1031 landed the six
adopted palettes plus high-contrast in light and dark, and this file is where
its acceptance criterion is met: **every** theme, **every** text token,
**every** surface it can land on.
"""

from __future__ import annotations

import pytest

# tests/ has no __init__.py, so pytest puts it on sys.path itself and this is a
# flat import rather than `tests.contrast`.
from contrast import INDICATOR_FLOOR, TEXT_FLOOR, contrast_ratio, relative_luminance
from lwsm.controller import ProjectStatus
from lwsm.theme import (
    DEFAULT_THEME,
    FOLLOW_SYSTEM,
    Theme,
    resolve_theme_id,
    theme_for_id,
)
from lwsm.theme import THEMES as PALETTES

# Derived from the registry, never listed: a palette added to `theme.py` and
# forgotten here would be a theme with no contrast test at all, which is the
# one failure § T8's "adding a theme that fails is a failing build" forbids.
THEMES = [pytest.param(theme, id=name) for name, theme in PALETTES.items()]

# § T8 holds the two assistive palettes to 7:1 on text pairs, "because a theme
# whose whole purpose is contrast has to be held to more than the floor
# everything else meets; softening them is the regression this tier exists to
# catch".
HIGH_CONTRAST_FLOOR = 7.0


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


# --- LWSM-1070: the focus ring has to be seen to be a focus ring --------------


@pytest.mark.parametrize("theme", THEMES)
def test_the_focus_ring_clears_the_indicator_floor(theme: Theme) -> None:
    ratio = contrast_ratio(theme.accent, theme.window)
    assert ratio >= INDICATOR_FLOOR, (
        f"the focus ring is {ratio:.2f}:1 against the window, below § T8's "
        f"{INDICATOR_FLOOR}:1 for a non-text indicator"
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
    `testing.md § T8` both require of a text pair.

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

    STOPPING is asserted to have NO token of its own, because `design.md
    § Tokens, not colours` gives it none — it is the optimistic overlay's
    transient label rather than a state derived from observation, and a token
    appearing for it later is a design change, not a fix.
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
