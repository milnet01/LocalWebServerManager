"""The outline and focus ring every Fusion control is drawn with.

UI layer: it imports `QtWidgets`. It names no colour — the outline is the
palette's `Mid` and the ring its `Highlight`, which `theme.Theme.to_palette`
binds to the `border` and `accent` tokens — so `theme.py` stays the one place
a colour is defined.
"""

from __future__ import annotations

from typing import cast

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QProxyStyle,
    QStyle,
    QStyleOption,
    QStyleOptionButton,
    QWidget,
)


def focus_ring_width(metrics: QFontMetrics) -> int:
    """How thick a focus ring is, from the text metric — never a pixel constant.

    One formula for the row and for every Fusion control, because the user
    chose one width for both (LWSM-1349, 2026-10-01). A fixed width would thin
    to a hairline under LWSM-1032's 200 % text-size control, which is the
    setting the users who depend on the ring are most likely to be running.
    """
    return max(1, round(metrics.height() / 8))


class OutlineStyle(QProxyStyle):
    """Fusion, with the theme's outline and a thick focus ring painted on top.

    `design-accessibility.md` promises outlines that clear 3:1 and a thick
    ring on every focusable control. Fusion draws neither: its outline is a
    shade derived from the window colour, so the `border` token reached no
    drawn frame (LWSM-1337), and its ring is 1-2 px at any text size
    (LWSM-1349).

    **A proxy, not a style-sheet border, and the user chose that.** A border
    in the style sheet hands the control to `QStyleSheetStyle`, which drops
    Fusion's shading and leaves every button flat; the user wanted the shading
    kept (2026-10-01). Painting AFTER Fusion keeps its rendering and its
    sizes, since nothing here changes a size hint.

    No colour is named here: the outline is the palette's `Mid` and the ring
    its `Highlight`, which `Theme.to_palette` binds to `border` and `accent`.
    So a theme switch needs nothing from this class.
    """

    # The panels that carry a control's outline. `PE_Frame` is the project
    # row and the settings dialog's folder list; the row paints its own ring
    # over this one, in the same width and colour.
    _PRIMITIVES = (
        QStyle.PrimitiveElement.PE_PanelLineEdit,
        QStyle.PrimitiveElement.PE_Frame,
    )
    _COMPLEX = (
        QStyle.ComplexControl.CC_ComboBox,
        QStyle.ComplexControl.CC_SpinBox,
    )

    # Two controls hold a CHILD widget that is painted after this style, over
    # the inner edge of the ring: a list's viewport sits 1 px in and a spin
    # box's text field 3 px in, so the ring showed 1 px of its 2 and 3 of its
    # 5 at 200 % (measured 2026-10-01). Each child is moved in by the ring's
    # width instead. Read when the widget is polished or resized, so a dialog
    # built after a text-size change gets the new width.

    def pixelMetric(self, metric, option=None, widget=None) -> int:
        value = super().pixelMetric(metric, option, widget)
        if metric == QStyle.PixelMetric.PM_DefaultFrameWidth and isinstance(
            widget, QAbstractScrollArea
        ):
            return max(value, focus_ring_width(widget.fontMetrics()))
        return value

    def subControlRect(self, control, option, sub, widget=None) -> QRect:
        # PySide6's stub types `widget` as required, but Qt's C++ default is
        # null and a null works here (measured 2026-10-01), so the cast tells
        # the type checker what the runtime already accepts.
        rect = super().subControlRect(control, option, sub, cast(QWidget, widget))
        if (
            control == QStyle.ComplexControl.CC_SpinBox
            and sub == QStyle.SubControl.SC_SpinBoxEditField
        ):
            inset = focus_ring_width(option.fontMetrics)
            rect = rect.intersected(option.rect.adjusted(inset, inset, -inset, -inset))
        return rect

    # A check box's ring goes round the whole control, which starts with the
    # indicator, so the ring sat ON the indicator's edge and hid its outline.
    # Fusion is handed the control's rect shrunk by the ring and a gap, so it
    # lays the indicator and the text out inside the ring, and the size grows
    # to match. Not by `subElementRect`: Fusion's own check box drawing asks
    # its own, never the proxy's (measured 2026-10-08).
    @staticmethod
    def check_box_inset(metrics: QFontMetrics) -> int:
        # Three pixels of the window between ring and indicator, so the ring
        # reads as round the control rather than as the indicator's edge.
        return focus_ring_width(metrics) + 3

    def sizeFromContents(self, kind, option, size, widget=None) -> QSize:
        grown = super().sizeFromContents(kind, option, size, cast(QWidget, widget))
        if kind == QStyle.ContentsType.CT_CheckBox:
            inset = self.check_box_inset(option.fontMetrics)
            grown = grown + QSize(2 * inset, 2 * inset)
        return grown

    def subElementRect(self, element, option, widget=None) -> QRect:
        rect = super().subElementRect(element, option, cast(QWidget, widget))
        if element == QStyle.SubElement.SE_CheckBoxClickRect:
            # What the user can click. Fusion's answer is for the un-grown
            # box, so it stopped short of the label drawn in the inset rect
            # (LWSM-1532). Asked of the inset rect, then widened back out to
            # the whole control, so the gap and the ring toggle it too. The
            # other check box sub-rects stay Fusion's: the tests ask them of
            # an already inset rect.
            inset = self.check_box_inset(option.fontMetrics)
            inner = QStyleOptionButton(option)
            inner.rect = option.rect.adjusted(inset, inset, -inset, -inset)
            rect = super().subElementRect(element, inner, cast(QWidget, widget))
            rect = rect.adjusted(-inset, -inset, inset, inset).intersected(option.rect)
        return rect

    def drawControl(self, element, option, painter, widget=None) -> None:
        if element == QStyle.ControlElement.CE_CheckBox:
            inset = self.check_box_inset(option.fontMetrics)
            inner = QStyleOptionButton(option)
            inner.rect = option.rect.adjusted(inset, inset, -inset, -inset)
            super().drawControl(element, inner, painter, widget)
        else:
            super().drawControl(element, option, painter, widget)
        if element == QStyle.ControlElement.CE_PushButtonBevel:
            # Held down, the button fills with `accent`, the ring's own colour
            # (LWSM-1485), so the ring is drawn in `base`, the text on that fill.
            held = bool(option.state & QStyle.StateFlag.State_Sunken)
            self._outline(option, painter, on_accent=held)
        elif element == QStyle.ControlElement.CE_CheckBox:
            # A check box has no frame to outline, so only the ring, round the
            # whole control (review-code 2026-10-08 L09-H1). Its outline is on
            # the indicator, below.
            self._outline(option, painter, resting=False)

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        super().drawPrimitive(element, option, painter, widget)
        # A frameless line edit — the one inside an editable combo box, say —
        # reports a zero line width and gets no outline, as under Fusion.
        if element in self._PRIMITIVES and getattr(option, "lineWidth", 1) > 0:
            self._outline(option, painter)
        elif element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            # Fusion's indicator edge is a shade of the window colour, so a
            # ticked box on a dark palette read as a bare tick (rendered on
            # midnight, 2026-10-08). Outlined always; the ring goes round the
            # whole control, not this small square.
            self._outline(option, painter, ring=False)

    def drawComplexControl(self, control, option, painter, widget=None) -> None:
        super().drawComplexControl(control, option, painter, widget)
        if control in self._COMPLEX and getattr(option, "frame", True):
            self._outline(option, painter)

    @staticmethod
    def _outline(
        option: QStyleOption,
        painter: QPainter,
        *,
        ring: bool = True,
        resting: bool = True,
        on_accent: bool = False,
    ) -> None:
        """The ring on keyboard focus, else the 1 px outline.

        `ring=False` for an element that never takes the ring itself, and
        `resting=False` for one with no outline of its own. `on_accent` for a
        control filled with the ring's colour: the ring is drawn in `Base`.
        """
        # Fusion's own test for showing focus: it needs the keyboard to have
        # moved it, so a click does not draw a ring (CLAUDE.md's
        # `QStyleOption` trap).
        state = option.state
        focused = (
            ring
            and bool(state & QStyle.StateFlag.State_HasFocus)
            and bool(state & QStyle.StateFlag.State_KeyboardFocusChange)
        )
        if focused:
            width = focus_ring_width(option.fontMetrics)
            palette = option.palette
            colour = palette.base() if on_accent else palette.highlight()
            pen = QPen(colour.color(), width)
        elif resting:
            width = 1
            pen = QPen(option.palette.mid().color(), width)
        else:
            return
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.save()
        # Square and unblended, so the edge pixel IS the token: an
        # antialiased line would be a mix of it and the surface, below the
        # contrast the token was solved for.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        # Inset by half the pen, which straddles the path it is given — the
        # row's reason in `ProjectRow.paintEvent`.
        inset = width / 2
        painter.drawRect(QRectF(option.rect).adjusted(inset, inset, -inset, -inset))
        painter.restore()


def install_outline_style(app: QApplication) -> None:
    """Put `OutlineStyle` on the application, once.

    On the APPLICATION, like the palette: the window's style sheet wraps the
    application style, so a style set on a widget would reach that widget
    alone. Idempotent because every window construction calls it, and
    `setStyle` re-polishes every widget in the process.

    **Before the palette is set, not after**: `setStyle` re-polishes, and the
    caller then sets the theme's palette over whatever that left.
    """
    if not isinstance(app.style(), OutlineStyle):
        app.setStyle(OutlineStyle("Fusion"))
