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
        return {
            ProjectStatus.RUNNING: self.state_running,
            ProjectStatus.STOPPED: self.state_stopped,
            ProjectStatus.UNKNOWN: self.state_unknown,
        }[status]

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
        return palette
