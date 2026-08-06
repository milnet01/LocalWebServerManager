"""WCAG 2.1 contrast arithmetic for `docs/standards/testing.md § T8`.

Not named `test_*`, so pytest imports it rather than collecting it.

§ T8 requires contrast to be *computed* over every theme rather than eyeballed,
which is what makes "adding a theme that fails is a failing build" true. It is
shared because two invariants need the same arithmetic: the focus ring's
visibility (LWSM-1070) and the state tokens' legibility (LWSM-1075).

The formula is WCAG 2.1's, transcribed from the specification rather than
recalled: relative luminance is the sRGB channel linearised at the 0.03928
threshold and weighted 0.2126 / 0.7152 / 0.0722, and contrast is
(lighter + 0.05) / (darker + 0.05).
"""

from __future__ import annotations

# § T8's two floors. Text is the stricter one because a state word is read, not
# merely noticed; a focus ring is a non-text indicator (WCAG 1.4.11 / 2.4.11).
TEXT_FLOOR = 4.5
INDICATOR_FLOOR = 3.0


def _channel(value: int) -> float:
    srgb = value / 255
    if srgb <= 0.03928:
        return srgb / 12.92
    return ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(channel * 2 for channel in raw)
    if len(raw) != 6:
        raise ValueError(f"not a 6-digit hex colour: {hex_colour!r}")
    red, green, blue = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground: str, background: str) -> float:
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)
