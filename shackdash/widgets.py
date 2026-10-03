"""Custom-painted instruments in the HamProjects "3D" look: raised metal
buttons with a drop shadow and glossy cap (they sink when pressed), LED
glow dots, recessed glowing LCD screens, and rounded fieldset panels with
the title inline on the border.  Ported from Rig Deck."""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QWidget

from .theme import Theme, px, shade

def qc(color: str, alpha: int | None = None) -> QColor:
    c = QColor(color)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def font(size_px: float, bold: bool = False, mono: bool = False) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(max(6, round(size_px)))
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


# ---- shared painting helpers ------------------------------------------------

def paint_recess(p: QPainter, r: QRectF, t: Theme, radius: float) -> None:
    """A screen sunk into the panel: dark fill, shadowed top/left inner edge,
    a faint light catch on the bottom/right lip."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qc(t.screen))
    p.drawRoundedRect(r, radius, radius)
    bevel = QLinearGradient(r.topLeft(), r.bottomRight())
    bevel.setColorAt(0.0, qc("#000000", 230))
    bevel.setColorAt(0.5, qc("#000000", 60))
    bevel.setColorAt(1.0, qc(shade(t.edge, 50), 200))
    p.setPen(QPen(bevel, max(1.5, px(2.2))))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)
    # soft inner shadow along the top edge
    top = QLinearGradient(r.left(), r.top(), r.left(), r.top() + px(10))
    top.setColorAt(0, qc("#000000", 120))
    top.setColorAt(1, qc("#000000", 0))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(top)
    p.drawRoundedRect(QRectF(r.left() + 2, r.top() + 2, r.width() - 4, px(10)), radius * 0.6, radius * 0.6)
    p.restore()


def paint_glow_dot(p: QPainter, c: QPointF, size: float, color: str, lit: bool, off: str) -> None:
    """The family glow_dot(): soft halo, solid core, small white highlight."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    r = size / 2
    if lit:
        halo = QRadialGradient(c, r * 1.6)
        halo.setColorAt(0, qc(color, 170))
        halo.setColorAt(0.5, qc(color, 60))
        halo.setColorAt(1, qc(color, 0))
        p.setBrush(halo)
        p.drawEllipse(c, r * 1.6, r * 1.6)
    core = QRadialGradient(QPointF(c.x() - r * 0.25, c.y() - r * 0.25), r)
    base = color if lit else off
    core.setColorAt(0, qc(shade(base, 70)))
    core.setColorAt(1, qc(base if lit else shade(off, -10)))
    p.setBrush(core)
    p.setPen(QPen(qc("#000000", 150), max(1.0, size * 0.08)))
    p.drawEllipse(c, r * 0.62, r * 0.62)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qc("#ffffff", 150 if lit else 40))
    p.drawEllipse(QPointF(c.x() - r * 0.2, c.y() - r * 0.22), r * 0.2, r * 0.16)
    p.restore()


# ---- containers --------------------------------------------------------------

class Fieldset(QFrame):
    """Thin rounded outline with the title inline on the top border (the
    family's rounded_panel(): an HTML fieldset/legend), optional glow dot."""

    def __init__(self, theme: Theme, title: str = "", dot: str | None = None, parent=None):
        super().__init__(parent)
        self.t = theme
        self.title = title
        self.dot = dot
        self.edge = theme.edge
        self.edge_w = 2

    def set_title(self, title: str, dot: str | None = None, edge: str | None = None, edge_w: int | None = None):
        new = (title, dot, edge or self.t.edge, edge_w or 2)
        if new != (self.title, self.dot, self.edge, self.edge_w):
            self.title, self.dot, self.edge, self.edge_w = new
            self.update()

    def margins(self, pad: int = 14):
        """Content margins that leave room for the border and inline title."""
        return px(pad), px(pad + (12 if self.title else 2)), px(pad), px(pad)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        fs = px(14)
        top = fs * 0.75 if self.title else 2
        w = px(self.edge_w)
        rect = QRectF(w / 2 + 1, top, self.width() - w - 2, self.height() - top - w / 2 - 1)
        p.setPen(QPen(qc(self.edge), w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, px(14), px(14))
        if self.title:
            p.setFont(font(fs, bold=True))
            tw = p.fontMetrics().horizontalAdvance(self.title)
            dot_w = px(16) if self.dot else 0
            x = px(18)
            p.fillRect(QRectF(x - px(6), 0, tw + dot_w + px(12), top * 2), qc(t.bg))
            if self.dot:
                paint_glow_dot(p, QPointF(x + px(6), top), px(12), self.dot, True, t.led_off)
            p.setPen(qc(t.text))
            p.drawText(QRectF(x + dot_w, 0, tw + 4, top * 2), Qt.AlignmentFlag.AlignVCenter, self.title)


class Screen(QFrame):
    """A recessed LCD screen; child widgets draw on top of it."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme

    def paintEvent(self, _):
        p = QPainter(self)
        paint_recess(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.t, px(10))


class LedLabel(QWidget):
    """A glow-dot lamp with a caption (BUSY / TX)."""

    def __init__(self, theme: Theme, text: str, parent=None):
        super().__init__(parent)
        self.t = theme
        self.text = text
        self.color = theme.main
        self.lit = False
        self.available = True
        self.setMinimumWidth(px(78))
        self.setMinimumHeight(px(26))

    def set_state(self, text: str, color: str, lit: bool, available: bool = True):
        if (text, color, lit, available) != (self.text, self.color, self.lit, self.available):
            self.text, self.color, self.lit, self.available = text, color, lit, available
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        h = self.height()
        paint_glow_dot(p, QPointF(h * 0.5, h / 2), h * 0.62, self.color, self.lit and self.available,
                       self.t.led_off)
        p.setFont(font(px(14), bold=True))
        p.setPen(qc(self.t.text if self.lit else (self.t.dim if self.available else self.t.faint)))
        p.drawText(QRectF(h, 0, self.width() - h, h), Qt.AlignmentFlag.AlignVCenter, self.text)


# ---- the 3D console button --------------------------------------------------------

class DeckButton(QWidget):
    """Raised rounded metal key: drop shadow, darker rim, glossy top cap.
    Held down it loses the shadow and sinks into its place. Toggle keys
    carry a small LED that glows when the function is on. Optional ‹ ›
    arrow zones (step -1 / +1), a small value line, and a right-click menu."""
    clicked = Signal()
    stepped = Signal(int)
    menuRequested = Signal()

    def __init__(self, theme: Theme, text: str, role: str = "teal", arrows: bool = False,
                 tall: bool = False, led: bool = False, parent=None):
        super().__init__(parent)
        self.t = theme
        self.text = text
        self.sub = ""
        self.role = role
        self.arrows = arrows
        self.tall = tall
        self.led = led
        self.active = False
        self.selected = False
        self.available = True
        self._pressed = None         # -1 left arrow, 0 body, +1 right arrow, None = not pressed
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(px(36))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, text=None, sub=None, active=None, selected=None, available=None, role=None, led=None):
        changed = False
        for name, val in (("text", text), ("sub", sub), ("active", active), ("selected", selected),
                          ("available", available), ("role", role), ("led", led)):
            if val is not None and getattr(self, name) != val:
                setattr(self, name, val)
                changed = True
        if changed:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.available else Qt.CursorShape.ArrowCursor)
            self.update()

    def _role_color(self) -> str:
        t = self.t
        return {"teal": t.teal_edge, "purple": t.purple, "amber": t.amber, "red": t.red,
                "green": t.main}.get(self.role, t.teal_edge)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        sdx, sdy = px(3), px(4)
        w, h = self.width() - sdx - 1, self.height() - sdy - 1
        rad = min(px(9), h * 0.3)
        pressed = self._pressed is not None and self.available
        role = self._role_color()
        if not self.available:
            base = shade(t.btn, -14)
        elif self.active and not self.led:
            base = shade(role, -70) if self.role != "red" else t.red
        elif self.active and self.role in ("red",):
            base = t.red
        else:
            base = t.btn

        if pressed:
            ox, oy = sdx * 0.7, sdy * 0.7
            body = QRectF(ox, oy, w, h)
            p.setPen(QPen(qc(shade(base, -55)), px(2)))
            p.setBrush(qc(shade(base, -18)))
            p.drawRoundedRect(body, rad, rad)
            cap = QRectF(body.left() + px(3), body.top() + px(3), body.width() - px(6), (h - px(6)) * 0.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(shade(base, -34)))
            p.drawRoundedRect(cap, max(2, rad - 3), max(2, rad - 3))
        else:
            body = QRectF(0.5, 0.5, w, h)
            if self.available:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qc("#000000", 115))
                p.drawRoundedRect(body.translated(sdx, sdy), rad, rad)
            g = QLinearGradient(body.topLeft(), body.bottomLeft())
            g.setColorAt(0, qc(shade(base, 10)))
            g.setColorAt(1, qc(shade(base, -16)))
            p.setBrush(g)
            edge = t.teal_edge if self.selected else shade(base, -45)
            p.setPen(QPen(qc(edge), px(2) if self.selected else px(1.6)))
            p.drawRoundedRect(body, rad, rad)
            if self.available:
                cap = QRectF(body.left() + px(3), body.top() + px(3), body.width() - px(6), (h - px(6)) * 0.42)
                cg = QLinearGradient(cap.topLeft(), cap.bottomLeft())
                cg.setColorAt(0, qc(shade(base, 48)))
                cg.setColorAt(1, qc(shade(base, 18)))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(cg)
                p.drawRoundedRect(cap, max(2, rad - 3), max(2, rad - 3))
        if self.active and self.available and not self.led and self.role != "red":
            # lit key: coloured rim glow
            p.setPen(QPen(qc(role, 200), px(1.6)))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), rad, rad)

        # LED indicator
        if self.led:
            d = max(px(13), h * 0.3)
            paint_glow_dot(p, QPointF(body.left() + d * 0.85, body.top() + d * 0.85), d, role,
                           self.active and self.available, t.led_off)

        ox, oy = body.left(), body.top()
        fs = min(px(15), h * (0.26 if self.tall else 0.42))
        txt_color = qc(t.faint) if not self.available else qc("#ffffff") if (self.active or pressed) else qc(t.text)
        if self.arrows:
            p.setFont(font(fs * 1.35, bold=True))
            p.setPen(qc(t.dim) if self.available else qc(t.faint))
            aw = w * 0.16
            p.drawText(QRectF(ox, oy, aw, h), Qt.AlignmentFlag.AlignCenter, "‹")
            p.drawText(QRectF(ox + w - aw, oy, aw, h), Qt.AlignmentFlag.AlignCenter, "›")
        p.setFont(font(fs * (1.3 if self.tall else 1.0), bold=True))
        # engraved text: dark shadow one pixel below
        def text(rect, flags, s, col):
            p.setPen(qc("#000000", 150))
            p.drawText(rect.translated(0, max(1, px(1))), flags, s)
            p.setPen(col)
            p.drawText(rect, flags, s)
        if self.sub:
            text(QRectF(ox, oy, w, h * 0.6), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                 self.text, txt_color)
            p.setFont(font(fs * 0.74, mono=True))
            sub_col = qc(role if self.active else t.teal_edge) if self.available else qc(t.faint)
            if self.active and not self.led:
                sub_col = qc("#ffffff")
            text(QRectF(ox, oy + h * 0.58, w, h * 0.38), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                 self.sub, sub_col)
        else:
            text(QRectF(ox, oy, w, h), Qt.AlignmentFlag.AlignCenter, self.text, txt_color)

    def _zone(self, x):
        if self.arrows:
            aw = self.width() * 0.2
            if x < aw:
                return -1
            if x > self.width() - aw:
                return 1
        return 0

    def mousePressEvent(self, e):
        if not self.available:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self.menuRequested.emit()
            return
        self._pressed = self._zone(e.position().x())
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pressed is None or not self.available or e.button() != Qt.MouseButton.LeftButton:
            return
        zone, self._pressed = self._pressed, None
        self.update()
        if not self.rect().contains(e.position().toPoint()):
            return
        if zone == 0:
            self.clicked.emit()
        else:
            self.stepped.emit(zone)

    def mouseDoubleClickEvent(self, e):
        if self.available and e.button() == Qt.MouseButton.LeftButton:
            zone = self._zone(e.position().x())
            self._pressed = zone
            self.update()

    def wheelEvent(self, e):
        if self.available:
            d = e.angleDelta().y()
            if d:
                self.stepped.emit(1 if d > 0 else -1)
        e.accept()


