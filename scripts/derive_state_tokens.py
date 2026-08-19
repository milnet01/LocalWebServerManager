"""Derive a palette's state tokens by measurement (LWSM-1031).

Not part of the gate and not imported by the app. This is the tool that
produced the state-token literals in `src/lwsm/theme.py`, kept so that adding
a ninth palette is a run of this script rather than an afternoon of guessing —
and so the values in that file have a reproducible provenance.

**The hue and saturation per state are the design decision this file exists to
record.** They are not derivable from the hex values they produced, and they
are what makes a state token *mean* something rather than merely be legible:
green for running, cyan for starting, amber for a wrong port, violet for a
foreign process, orange for a blocked one, red for failed, grey for stopped,
olive for no observation at all.

**The lightness is walked AWAY from the palette's surfaces and stopped at the
first value that clears the floor.** Walking from the far end instead returns
near-white for every hue on a dark palette — that draft passed every contrast
check in `tests/test_theme.py` while carrying no state information, which is
the trap `CLAUDE.md` records and
`test_the_state_tokens_are_distinguishable_from_the_body_text` catches.

Usage:

    uv run python scripts/derive_state_tokens.py

It prints the token block for every palette in `theme.THEMES`, with each
measured ratio as a trailing comment, and reports any FIXED token (`text`,
`muted_text`, `attention`) that falls short — which is how the four
divergences from finbreak were found.
"""

from __future__ import annotations

import colorsys
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from contrast import INDICATOR_FLOOR, TEXT_FLOOR, contrast_ratio
from lwsm.theme import THEMES

# The 7:1 floor `docs/standards/testing.md § T8` holds the two assistive
# palettes to. Kept here rather than imported from the test, so running this
# script needs nothing but the arithmetic.
HIGH_CONTRAST_FLOOR = 7.0

# Hue (0-1) and saturation per state — see the module docstring. One per
# ADR-0004 derived state, plus `state_unknown`, which is not one of the seven.
STATES: dict[str, tuple[float, float]] = {
    "state_running": (0.36, 0.70),
    "state_starting": (0.55, 0.65),
    "state_wrong_port": (0.11, 0.85),
    "state_foreign": (0.75, 0.45),
    "state_blocked": (0.06, 0.80),
    "state_failed": (0.01, 0.70),
    "state_stopped": (0.60, 0.06),
    "state_unknown": (0.13, 0.65),
}

# Every surface a token can land on. `alt_base` is included although no widget
# paints it yet: the day one does is not the day to discover the pair fails.
SURFACES = ("window", "base", "alt_base")


def hex_of(hue: float, lightness: float, saturation: float) -> str:
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def solve(
    hue: float, saturation: float, backgrounds: list[str], floor: float, dark: bool
) -> tuple[str, float]:
    """The first value clearing `floor` against the WORST of `backgrounds`.

    Ascending from black on a dark palette, descending from white on a light
    one — away from the surfaces, so the token keeps as much of its hue as the
    floor allows. See the module docstring for what the other direction does.
    """
    steps = range(0, 1001) if dark else range(1000, -1, -1)
    best = ("", 0.0)
    for step in steps:
        candidate = hex_of(hue, step / 1000, saturation)
        worst = min(contrast_ratio(candidate, bg) for bg in backgrounds)
        if worst >= floor:
            return candidate, worst
        if worst > best[1]:
            best = (candidate, worst)
    return best


def main() -> int:
    shortfalls = 0
    for name, theme in THEMES.items():
        floor = HIGH_CONTRAST_FLOOR if theme.high_contrast else TEXT_FLOOR
        backgrounds = [getattr(theme, surface) for surface in SURFACES]

        print(f'    "{name}": Theme(')
        for token, (hue, saturation) in STATES.items():
            value, ratio = solve(hue, saturation, backgrounds, floor, theme.is_dark)
            print(f'        {token}="{value}",  # {ratio:.2f}:1')
        print("    ),")

        for token in ("text", "muted_text", "attention"):
            for surface in SURFACES:
                ratio = contrast_ratio(getattr(theme, token), getattr(theme, surface))
                if ratio < floor:
                    shortfalls += 1
                    print(
                        f"# SHORTFALL {name}: {token}/{surface} = {ratio:.2f} "
                        f"(floor {floor})"
                    )
        ratio = contrast_ratio(theme.accent, theme.window)
        if ratio < INDICATOR_FLOOR:
            shortfalls += 1
            print(f"# SHORTFALL {name}: accent/window = {ratio:.2f} (indicator floor)")

    print(f"\n# {shortfalls} shortfall(s) in the fixed tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
