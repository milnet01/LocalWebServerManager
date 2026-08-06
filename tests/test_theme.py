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
