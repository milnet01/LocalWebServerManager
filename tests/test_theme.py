"""LWSM-1005 INV-17 — `docs/standards/testing.md § T8` contrast arithmetic.

Computed over the palette rather than eyeballed, so that when LWSM-1031 lands
the remaining six palettes plus high-contrast, adding one that fails is a
failing build rather than a discovery months later.
"""

from __future__ import annotations

import pytest

# tests/ has no __init__.py, so pytest puts it on sys.path itself and this is a
# flat import rather than `tests.contrast`.
from contrast import INDICATOR_FLOOR, TEXT_FLOOR, contrast_ratio, relative_luminance
from lwsm.controller import ProjectStatus
from lwsm.theme import Theme

# LWSM-1031 appends its palettes here and inherits every check below.
THEMES = [pytest.param(Theme.default(), id="default")]


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
    "state_running",
    "state_stopped",
    "state_unknown",
]


@pytest.mark.parametrize("token", TEXT_TOKENS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_text_token_clears_the_text_floor(theme: Theme, token: str) -> None:
    """This is the *default* palette, so a failure here is what a first run
    gets — not an edge case behind a setting."""
    ratio = contrast_ratio(getattr(theme, token), theme.window)
    assert ratio >= TEXT_FLOOR, (
        f"{token} is {ratio:.2f}:1 against the window, below § T8's "
        f"{TEXT_FLOOR}:1 for a text pair"
    )


@pytest.mark.parametrize("theme", THEMES)
def test_body_text_clears_the_floor_on_the_base_surface(theme: Theme) -> None:
    """`window` is not the only background a token lands on: `base` is what
    LWSM-1007's list view and P05's inputs will paint under."""
    assert contrast_ratio(theme.text, theme.base) >= TEXT_FLOOR
    assert contrast_ratio(theme.text, theme.alt_base) >= TEXT_FLOOR


# --- LWSM-1077: the theme owes a style sheet, not just a palette --------------


@pytest.mark.parametrize("theme", THEMES)
def test_the_style_sheet_carries_every_state(theme: Theme) -> None:
    """`design.md § Tokens, not colours` gives a Theme two outputs. Only the
    palette existed, so widget code composed the CSS itself."""
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
