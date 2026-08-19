"""Semantic colour tokens. The only module in the UI layer holding a colour.

`docs/standards/coding.md § O7`: a widget names a token, never a colour. This
is the token *definition* site, so the values necessarily live here — which is
why `tests/test_layering.py` exempts this one file and no other.

Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`. LWSM-1031 landed the
six palettes plus high-contrast in light and dark; P02 had one, to prove
widgets name tokens.

**The six are transcribed from finbreak, not invented** —
`finbreak/src/finbreak/ui/theme.py`, ADR-0010 there. Transcribed rather than
imported because a public repository cannot depend on a path outside it. Where
a transcribed value fails this project's contrast floors it is adjusted here
and the divergence recorded beside it: finbreak tuned `muted_text` against
`window` alone, and `alt_base` is a darker surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

from lwsm.controller import ProjectStatus


@dataclass(frozen=True)
class Theme:
    """The nine base tokens adopted from finbreak, plus this project's states.

    `docs/design.md § Tokens, not colours` defines the base nine and says
    ADR-0004's seven derived states define the state-token set.
    """

    # The theme's own name, for the picker. Data, not `tr()`-wrapped: a
    # palette id is not a sentence, and finbreak's INV-13 makes the same call.
    label: str

    window: str
    base: str
    alt_base: str
    text: str
    muted_text: str
    accent: str
    accent_soft: str
    attention: str
    border: str
    is_dark: bool

    # `docs/standards/testing.md § T8` holds these two to **7:1** rather than
    # 4.5:1. A flag on the theme rather than a set of ids kept beside it: the
    # floor a palette is judged against is a property of the palette, and a
    # separate set is a second place to forget to update.
    high_contrast: bool

    # One per ADR-0004 derived state (`design.md § Tokens, not colours` is
    # canonical), plus `state_unknown`, which is not one of the seven: it means
    # no observation is available, and ADR-0004 lists states derived FROM one.
    #
    # Four of the seven have no `ProjectStatus` to bind to yet — LWSM-1011 adds
    # those states. They are defined here anyway, and deliberately: the cost of
    # a state token is tuning it against three surfaces on eight palettes, so
    # adding the states later without the colours means re-opening every
    # palette. `state_token` maps what exists; the contrast test covers all of
    # them from the day they land.
    state_running: str
    state_starting: str
    state_wrong_port: str
    state_foreign: str
    state_blocked: str
    state_failed: str
    state_stopped: str
    state_unknown: str

    @classmethod
    def default(cls) -> Theme:
        """What a first run gets with no settings file — **dark** (LWSM-1147).

        LWSM-1031 resolves follow-system to midnight or ledger; the user asked
        for dark unconditionally, which is a different rule, because
        follow-system on a light desktop opens light. So follow-system becomes
        a choice rather than the starting state, and this is `midnight`.

        The light placeholder this used to return was LWSM-1005's single
        palette, built to prove widgets name tokens. `ledger`, `parchment` and
        `mint` are the light palettes now, so keeping it would have made "six
        themes" false and given the picker a seventh entry nobody specified.
        Its one tuned value is not lost: `state_unknown` was darkened to
        #856819 under LWSM-1075 against a #f4f4f6 window, and every palette
        below is tuned by the same arithmetic against its own surfaces.
        """
        return THEMES[DEFAULT_THEME]

    def focus_ring_color(self) -> QColor:
        """The focus ring is the accent, expanded here rather than in the widget.

        A widget may not name a colour or build a `QColor` (`§ O7`, enforced by
        `tests/test_layering.py`), so the token is expanded at the definition
        site. Binding the ring to `accent` rather than giving it a token of its
        own means every palette gets a legible ring from the contrast it
        already has to prove for its accent.
        """
        return QColor(self.accent)

    def state_color(self, status: ProjectStatus) -> QColor:
        """The state token as a `QColor`, for the painted glyph (LWSM-1071).

        Same reason as `focus_ring_color`: `§ O7` forbids widget code from
        constructing a colour, so anything painted rather than styled needs its
        token expanded here.
        """
        return QColor(self.state_token(status))

    def state_token(self, status: ProjectStatus) -> str:
        # .get, not [...]: same reason as the glyph lookup in mainwindow — this
        # is reached from a signal handler, and LWSM-1011 adds four states. A
        # state with no token of its own reads in the ordinary text colour
        # rather than crashing the window.
        # STOPPING is absent on purpose and is not an oversight: `design.md
        # § Tokens, not colours` gives it no token, because it is the optimistic
        # overlay's transient label rather than a state derived from
        # observation. It falls through to `text`, which is what the `.get`
        # default is for.
        return {
            ProjectStatus.RUNNING: self.state_running,
            ProjectStatus.STARTING: self.state_starting,
            ProjectStatus.STOPPED: self.state_stopped,
            ProjectStatus.UNKNOWN: self.state_unknown,
        }.get(status, self.text)

    # The dynamic property a state-carrying widget sets, and the selector the
    # generated style sheet matches on. Named here because both ends must agree
    # and only one of them is in this file.
    STATE_PROPERTY = "lwsmState"

    def style_sheet(self) -> str:
        """The app's style sheet, generated from the tokens (LWSM-1077).

        `docs/design.md § Tokens, not colours` gives a `Theme` two outputs — a
        `QPalette` **and** a generated style sheet, finbreak's two-layer split.
        Only the palette existed, so `mainwindow.py` was hand-building
        `f"color: {token};"` and calling `setStyleSheet` per row per tick. INV-8b
        still passed, because there was no colour *literal*; the layer the design
        asked for was simply absent and its job had leaked into widget code,
        which is what `§ O7` prevents one level up.

        Selecting on a dynamic property rather than emitting one rule per widget
        means the sheet is a constant of the theme: it is set once on the window,
        and a row changing state sets a property instead of composing CSS.
        """
        return "\n".join(
            f'QLabel[{self.STATE_PROPERTY}="{status.value}"] '
            f"{{ color: {self.state_token(status)}; }}"
            for status in ProjectStatus
        )

    def to_palette(self) -> QPalette:
        """Tokens expand into a QPalette so native widgets follow the theme.

        True only once the palette is set on the **QApplication**. Setting it on
        a window that also carries a style sheet themes the frame and nothing
        inside it, and this sentence was false for three reviews on that
        account — see INV-24 and `MainWindow.__init__` (LWSM-1118).
        """
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(self.window))
        palette.setColor(QPalette.ColorRole.Base, QColor(self.base))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(self.alt_base))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(self.text))
        palette.setColor(QPalette.ColorRole.Text, QColor(self.text))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(self.muted_text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(self.accent))
        palette.setColor(QPalette.ColorRole.Mid, QColor(self.border))
        # Four roles that were left at the style default, so P05's buttons and
        # tooltips would not have followed the theme (LWSM-1077).
        palette.setColor(QPalette.ColorRole.Button, QColor(self.window))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(self.text))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(self.base))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.base))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(self.text))
        return palette


# The eight palettes, keyed by the id stored in settings.json. Insertion order
# is the picker's order: the three light ones finbreak ships, the three dark,
# then the two assistive palettes last because they are a tool rather than a
# taste.
#
# **Every state token below was solved for, not chosen.** Each keeps a fixed
# hue and saturation for its meaning — green running, cyan starting, amber
# wrong-port, violet foreign, orange blocked, red failed, grey stopped, olive
# unknown — and its lightness is walked away from the palette's surfaces until
# the WORST of its three pairs (window, base, alt_base) clears the floor, then
# stopped. Walking from the far end instead returns near-white for every hue on
# a dark palette, which is legible and carries no meaning at all. The measured
# ratio is beside each value; `tests/test_theme.py` recomputes all of them, so
# a comment that drifts from its colour is a failing build rather than a lie.
THEMES: dict[str, Theme] = {
    "ledger": Theme(
        label="Ledger",
        window="#f5f4ef",
        base="#ffffff",
        alt_base="#efece2",
        text="#1b2a44",
        # Diverged from finbreak's #69707d: that is 4.22:1 on this
        # palette's alt_base, under § T8's 4.5:1. 4.52:1 here, hue kept.
        muted_text="#656b78",
        accent="#b2842a",
        accent_soft="#e6d5a3",
        attention="#a53a24",
        border="#d8d3c4",
        is_dark=False,
        high_contrast=False,
        state_running="#167c26",  # 4.50:1
        state_starting="#207296",  # 4.55:1
        state_wrong_port="#8f620c",  # 4.53:1
        state_foreign="#8751bd",  # 4.51:1
        state_blocked="#b14c14",  # 4.54:1
        state_failed="#ca2e24",  # 4.52:1
        state_stopped="#666b73",  # 4.54:1
        state_unknown="#7f691b",  # 4.51:1
    ),
    "parchment": Theme(
        label="Parchment",
        window="#efe6d3",
        base="#f9f2e2",
        alt_base="#e6dac2",
        text="#4a3b2a",
        # Diverged from finbreak's #726552: that is 4.10:1 on this
        # palette's alt_base, under § T8's 4.5:1. 4.50:1 here, hue kept.
        muted_text="#6b5f4d",
        accent="#b06d1f",
        accent_soft="#e0c48f",
        attention="#96331d",
        border="#d0c2a4",
        is_dark=False,
        high_contrast=False,
        state_running="#147022",  # 4.50:1
        state_starting="#1d6787",  # 4.54:1
        state_wrong_port="#81590a",  # 4.51:1
        state_foreign="#7c44b4",  # 4.54:1
        state_blocked="#a04512",  # 4.52:1
        state_failed="#b72920",  # 4.53:1
        state_stopped="#5c6168",  # 4.51:1
        state_unknown="#725f18",  # 4.51:1
    ),
    "mint": Theme(
        label="Mint",
        window="#f1f7f3",
        base="#ffffff",
        alt_base="#e6f1ea",
        text="#16302a",
        # Diverged from finbreak's #5c766b: that is 4.26:1 on this
        # palette's alt_base, under § T8's 4.5:1. 4.50:1 here, hue kept.
        muted_text="#597267",
        accent="#1f9d55",
        accent_soft="#bce7cd",
        attention="#b03a1e",
        border="#cde0d4",
        is_dark=False,
        high_contrast=False,
        state_running="#167d27",  # 4.54:1
        state_starting="#207498",  # 4.52:1
        state_wrong_port="#90630c",  # 4.56:1
        state_foreign="#8853be",  # 4.50:1
        state_blocked="#b34d14",  # 4.55:1
        state_failed="#cd2e24",  # 4.52:1
        state_stopped="#676d74",  # 4.52:1
        state_unknown="#816a1b",  # 4.52:1
    ),
    "midnight": Theme(
        label="Midnight",
        window="#131a2b",
        base="#0d1320",
        alt_base="#1b2336",
        text="#e6e9f0",
        muted_text="#8b93a7",
        accent="#d4af37",
        accent_soft="#6b5d2e",
        attention="#e0654f",
        border="#2a3450",
        is_dark=True,
        high_contrast=False,
        state_running="#1c9f31",  # 4.52:1
        state_starting="#2993c1",  # 4.50:1
        state_wrong_port="#b87f0f",  # 4.54:1
        state_foreign="#a278cc",  # 4.55:1
        state_blocked="#e46219",  # 4.52:1
        state_failed="#e26058",  # 4.51:1
        state_stopped="#848a92",  # 4.50:1
        state_unknown="#a38723",  # 4.51:1
    ),
    "graphite": Theme(
        label="Graphite",
        window="#23262b",
        base="#1a1c20",
        alt_base="#2b2f35",
        text="#dfe2e6",
        # Diverged from finbreak's #8a9099: that is 4.18:1 on this
        # palette's alt_base, under § T8's 4.5:1. 4.51:1 here, hue kept.
        muted_text="#90969e",
        accent="#5b7fb5",
        accent_soft="#34435c",
        attention="#e2775c",
        border="#3a3f47",
        is_dark=True,
        high_contrast=False,
        state_running="#1ead35",  # 4.54:1
        state_starting="#2ca0d1",  # 4.52:1
        state_wrong_port="#c88910",  # 4.51:1
        state_foreign="#ab86d1",  # 4.52:1
        state_blocked="#e87534",  # 4.50:1
        state_failed="#e5746c",  # 4.51:1
        state_stopped="#91969d",  # 4.52:1
        state_unknown="#b29326",  # 4.55:1
    ),
    "emerald": Theme(
        label="Emerald",
        window="#102019",
        base="#0a1712",
        alt_base="#172b22",
        text="#dcece4",
        muted_text="#7d9a8c",
        accent="#1fae6a",
        accent_soft="#2a5a44",
        attention="#e8836a",
        border="#234636",
        is_dark=True,
        high_contrast=False,
        state_running="#1da332",  # 4.51:1
        state_starting="#2a97c5",  # 4.51:1
        state_wrong_port="#bd820f",  # 4.53:1
        state_foreign="#a47ccd",  # 4.51:1
        state_blocked="#e6671f",  # 4.50:1
        state_failed="#e3665e",  # 4.50:1
        state_stopped="#888e96",  # 4.52:1
        state_unknown="#a88b24",  # 4.54:1
    ),
    "highcontrast-light": Theme(
        label="High contrast (light)",
        window="#ffffff",
        base="#ffffff",
        alt_base="#f2f2f2",
        text="#000000",
        muted_text="#3d3d3d",
        accent="#0000cc",
        accent_soft="#d6d6ff",
        attention="#a00000",
        border="#000000",
        is_dark=False,
        high_contrast=True,
        state_running="#115f1d",  # 7.00:1
        state_starting="#185772",  # 7.09:1
        state_wrong_port="#6d4b09",  # 7.05:1
        state_foreign="#6a3a99",  # 7.00:1
        state_blocked="#883b0f",  # 7.00:1
        state_failed="#9c231c",  # 7.02:1
        state_stopped="#4e5258",  # 7.02:1
        state_unknown="#615015",  # 7.03:1
    ),
    "highcontrast-dark": Theme(
        label="High contrast (dark)",
        window="#000000",
        base="#000000",
        alt_base="#141414",
        text="#ffffff",
        muted_text="#d0d0d0",
        accent="#ffff00",
        accent_soft="#3a3a00",
        attention="#ff8080",
        border="#ffffff",
        is_dark=True,
        high_contrast=True,
        state_running="#21b839",  # 7.00:1
        state_starting="#43abd7",  # 7.06:1
        state_wrong_port="#d59311",  # 7.03:1
        state_foreign="#b492d5",  # 7.03:1
        state_blocked="#eb854b",  # 7.01:1
        state_failed="#e8847d",  # 7.04:1
        state_stopped="#9ba0a7",  # 7.00:1
        state_unknown="#bd9d28",  # 7.03:1
    ),
}

# LWSM-1147. `Theme.default` explains why this is a dark theme rather than
# follow-system.
DEFAULT_THEME = "midnight"


def theme_for_id(theme_id: str) -> Theme:
    """The theme `theme_id` names, or the default when it names nothing.

    Falling back rather than raising, and this is the layer that owns the
    decision: `settings.py` stores the id as an opaque bounded string because
    a core module may not import this one (`coding.md § O1`). So an id for a
    theme a later build removed — or one a user hand-typed — arrives here, and
    a `KeyError` here is a window that does not open. The user gets the default
    palette instead, which is the one outcome that is certainly usable.
    """
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])
