"""WCAG 2.1 contrast arithmetic for `docs/standards/testing-overrides.md § T8`.

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
# § T8 holds the two assistive palettes to 7:1 on text pairs, "because a theme
# whose whole purpose is contrast has to be held to more than the floor
# everything else meets". Here beside the other two so the test and
# `scripts/derive_state_tokens.py` cannot hold different values (LWSM-1278).
HIGH_CONTRAST_FLOOR = 7.0


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


# LWSM-1338: the least CIEDE2000 difference between any two state tokens in
# one palette. All seven states can sit in one list, so every pair counts, not
# only the ones the ADR puts side by side. 15 is well past the ~10 at which two
# colours read as clearly different; the author's choice, open to the user's.
STATE_SEPARATION = 15.0


def _lab(hex_colour: str) -> tuple[float, float, float]:
    """sRGB to CIELAB under D65, the standard conversion."""
    rgb = [_channel(int(hex_colour[i : i + 2], 16)) for i in (1, 3, 5)]
    x = (0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]) / 0.95047
    y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    z = (0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e2000(first: str, second: str) -> float:
    """CIEDE2000 colour difference (Sharma, Wu and Dalal's formulation)."""
    import math

    l1, a1, b1 = _lab(first)
    l2, a2, b2 = _lab(second)
    c_bar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_bar**7 / (c_bar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dlp, dcp = l2 - l1, c2p - c1p
    dh = 0.0 if c1p * c2p == 0 else h2p - h1p
    if dh > 180:
        dh -= 360
    elif dh < -180:
        dh += 360
    dhp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    lbp, cbp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(hbp - 30))
        + 0.24 * math.cos(math.radians(2 * hbp))
        + 0.32 * math.cos(math.radians(3 * hbp + 6))
        - 0.20 * math.cos(math.radians(4 * hbp - 63))
    )
    rotation = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbp**7 / (cbp**7 + 25**7))
    sl = 1 + 0.015 * (lbp - 50) ** 2 / math.sqrt(20 + (lbp - 50) ** 2)
    sc = 1 + 0.045 * cbp
    sh = 1 + 0.015 * cbp * t
    rt = -math.sin(math.radians(2 * rotation)) * rc
    return math.sqrt(
        (dlp / sl) ** 2
        + (dcp / sc) ** 2
        + (dhp / sh) ** 2
        + rt * (dcp / sc) * (dhp / sh)
    )
