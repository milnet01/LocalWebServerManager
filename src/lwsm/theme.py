"""Semantic colour tokens. The only module in the UI layer holding a colour.

`docs/standards/coding.md § O7`: a widget names a token, never a colour. This
is the token *definition* site, so the values necessarily live here — which is
why `tests/test_layering.py` exempts this one file and no other.

Contract: `docs/specs/LWSM-1005-vertical-slice.md § 4.4`. LWSM-1031 lands the
six palettes plus high-contrast; P02 needs one, to prove widgets name tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette

from lwsm.controller import ProjectStatus


@dataclass(frozen=True)
class Theme:
    """The nine base tokens adopted from finbreak, plus the three P02 renders.

    `docs/design.md § Tokens, not colours` defines the base nine and says
    ADR-0004's seven derived states define the state-token set. P02 renders
    three: `state_running` is provisionally bound to the collapsed running
    state and LWSM-1011 re-points it to state_foreign / state_blocked;
    `state_unknown` is P02-local, since ADR-0004 lists states derived from
    observation and UNKNOWN is the absence of one.
    """

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
    state_running: str
    state_stopped: str
    state_unknown: str

    @classmethod
    def default(cls) -> Theme:
        """The light palette — what a first run gets with no settings file."""
        return cls(
            window="#f4f4f6",
            base="#ffffff",
            alt_base="#ececed",
            text="#1b1b1f",
            muted_text="#5a5a63",
            accent="#2f5bd0",
            accent_soft="#dce4f8",
            attention="#b3521a",
            border="#c4c4cc",
            is_dark=False,
            state_running="#1a7f3c",
            state_stopped="#5a5a63",
            # Darkened from #8a6d1f under LWSM-1075: that value computed to
            # 4.46:1 against `window`, under § T8's 4.5:1 text floor, and this
            # is the palette a first run gets. 4.79:1 leaves a margin rather
            # than sitting on the line the way state_running does at 4.61:1.
            state_unknown="#856819",
        )

    def focus_ring_color(self) -> QColor:
        """The focus ring is the accent, expanded here rather than in the widget.

        A widget may not name a colour or build a `QColor` (`§ O7`, enforced by
        `tests/test_layering.py`), so the token is expanded at the definition
        site. Binding the ring to `accent` rather than giving it a token of its
        own means every palette LWSM-1031 adds gets a legible ring from the
        contrast it already has to prove for its accent.
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
        return {
            ProjectStatus.RUNNING: self.state_running,
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
        """Tokens expand into a QPalette so native widgets follow the theme."""
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
