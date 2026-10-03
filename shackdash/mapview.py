"""World map on a recessed screen: equirectangular, centred on the QTH's
longitude, land from Natural Earth, day/night shading with the grey line,
plus markers, great-circle paths, tracks and an optional heat overlay."""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import astro
from .theme import Theme, px, shade
from .widgets import font, paint_glow_dot, paint_recess, qc


class MapView(QWidget):
    clicked = Signal(float, float)          # lat, lon

    def __init__(self, theme: Theme, center_lon: float = 0.0, lat_range=(-90.0, 90.0), lon_span: float = 360.0,
                 parent=None):
        super().__init__(parent)
        self.t = theme
        self.center_lon = center_lon
        self.lat_lo, self.lat_hi = lat_range
        self.span = lon_span
        self.land: list = []
        self._land_path: QPainterPath | None = None
        self._bg: QPixmap | None = None
        self.night = True
        self.markers: list[tuple] = []       # (lat, lon, color, label, size)
        self.paths: list[tuple] = []         # ([(lat,lon)...], color, width, dashed)
        self.heat: tuple | None = None       # (np grid [181,360] 0..100, color)
        self.caption = ""
        self._night_img: QImage | None = None
        self._night_key = None
        self.setMinimumSize(px(300), px(160))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

    # ---- data -------------------------------------------------------------------
    def set_land(self, polys):
        self.land = polys or []
        self._land_path = None
        self._bg = None
        self.update()

    def set_center(self, lon: float):
        if abs(lon - self.center_lon) > 0.01:
            self.center_lon = lon
            self._land_path = None
            self._bg = None
            self._night_key = None
            self.update()

    def set_overlays(self, markers=None, paths=None, heat=None, caption=None):
        if markers is not None:
            self.markers = markers
        if paths is not None:
            self.paths = paths
        if heat is not None:
            self.heat = heat if heat != () else None
        if caption is not None:
            self.caption = caption
        self.update()

    # ---- geometry ---------------------------------------------------------------
    def _frame(self) -> QRectF:
        r = QRectF(self.rect()).adjusted(px(6), px(6), -px(6), -px(6))
        aspect = self.span / (self.lat_hi - self.lat_lo)
        if r.width() / r.height() > aspect:
            w = r.height() * aspect
            return QRectF(r.center().x() - w / 2, r.top(), w, r.height())
        h = r.width() / aspect
        return QRectF(r.left(), r.center().y() - h / 2, r.width(), h)

    def xlon(self, lon: float) -> float:
        """Map longitude to the [-180, 180) window centred on center_lon."""
        return (lon - self.center_lon + 540) % 360 - 180

    def to_px(self, lat: float, lon: float, f: QRectF | None = None) -> QPointF:
        f = f or self._frame()
        x = f.left() + (self.xlon(lon) + self.span / 2) / self.span * f.width()
        y = f.top() + (self.lat_hi - lat) / (self.lat_hi - self.lat_lo) * f.height()
        return QPointF(x, y)

    def _build_land(self):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        for poly in self.land:
            # unwrap longitudes so a polygon never jumps across the seam, then draw
            # it at -360/0/+360 and let the clip rectangle cut it
            xs = []
            prev = None
            for lon, lat in poly:
                x = self.xlon(lon)
                if prev is not None:
                    while x - prev > 180:
                        x -= 360
                    while x - prev < -180:
                        x += 360
                xs.append((x, lat))
                prev = x
            for off in (-360, 0, 360):
                sub = QPainterPath()
                sub.moveTo(xs[0][0] + off, -xs[0][1])
                for x, lat in xs[1:]:
                    sub.lineTo(x + off, -lat)
                sub.closeSubpath()
                path.addPath(sub)
        self._land_path = path

    def _background(self, f: QRectF) -> QPixmap:
        size = self.size()
        if self._bg is not None and self._bg.size() == size:
            return self._bg
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        paint_recess(p, QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), t, px(10))
        p.save()
        p.setClipRect(f)
        ocean = QColor(shade(t.screen, 6))
        p.fillRect(f, ocean)
        if self._land_path is None and self.land:
            self._build_land()
        tr = QTransform()
        tr.translate(f.left() + f.width() / 2, f.top() + self.lat_hi / (self.lat_hi - self.lat_lo) * f.height())
        tr.scale(f.width() / self.span, f.height() / (self.lat_hi - self.lat_lo))
        if self._land_path is not None:
            p.setTransform(tr)
            p.setBrush(qc(shade(t.edge, -8)))
            pen = QPen(qc(shade(t.teal_edge, -40), 170), 0)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.drawPath(self._land_path)
            p.resetTransform()
        # graticule
        pen = QPen(qc(shade(t.screen, 34), 150), 1, Qt.PenStyle.DotLine)
        p.setPen(pen)
        for lat in range(-60, 90, 30):
            if self.lat_lo < lat < self.lat_hi:
                y = self.to_px(lat, 0, f).y()
                p.drawLine(QPointF(f.left(), y), QPointF(f.right(), y))
        for lon in range(-180, 180, 30):
            x = self.to_px(0, lon, f).x()
            p.drawLine(QPointF(x, f.top()), QPointF(x, f.bottom()))
        p.setPen(QPen(qc(shade(t.screen, 50), 200), 1))
        y = self.to_px(0, 0, f).y()
        if self.lat_lo < 0 < self.lat_hi:
            p.drawLine(QPointF(f.left(), y), QPointF(f.right(), y))
        p.restore()
        p.end()
        self._bg = pm
        return pm

    def _night_image(self, now: float) -> QImage:
        key = (int(now // 60), round(self.center_lon, 1), self.lat_lo, self.lat_hi)
        if self._night_img is not None and key == self._night_key:
            return self._night_img
        s = astro.sun(now)
        slat, slon = astro.subpoint(s)
        W, H = int(self.span), int(self.lat_hi - self.lat_lo)
        lons = (np.arange(W) + 0.5 - self.span / 2 + self.center_lon)
        lats = self.lat_hi - (np.arange(H) + 0.5)
        LA, LO = np.meshgrid(np.radians(lats), np.radians(lons), indexing="ij")
        d = math.radians(slat)
        alt = np.degrees(np.arcsin(np.sin(LA) * math.sin(d) + np.cos(LA) * math.cos(d) * np.cos(LO - math.radians(slon))))
        dark = np.clip(-alt / 12.0, 0, 1)            # twilight ramp to full night at -12 deg
        a = (dark * 150).astype(np.uint8)
        grey = np.exp(-((alt + 3) / 3.2) ** 2)          # the grey-line band around sunrise/sunset
        amber = QColor(self.t.amber)
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        g = (grey * 70).astype(np.uint8)
        # premultiplied ARGB: night = black with alpha, grey line = faint amber glow
        alpha = np.maximum(a, g)
        rgba[..., 3] = alpha
        rgba[..., 0] = (amber.blue() * grey * 70 / 255).astype(np.uint8)
        rgba[..., 1] = (amber.green() * grey * 70 / 255).astype(np.uint8)
        rgba[..., 2] = (amber.red() * grey * 70 / 255).astype(np.uint8)
        img = QImage(rgba.tobytes(), W, H, W * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()
        self._night_img, self._night_key = img, key
        return img

    def _heat_image(self) -> QImage | None:
        if not self.heat:
            return None
        grid, color = self.heat
        c = QColor(color)
        rows = []
        for lat in range(int(self.lat_hi), int(self.lat_lo), -1):
            rows.append(grid[lat + 90 - 1] if lat + 90 - 1 >= 0 else grid[0])
        g = np.array(rows, dtype=np.float32)                  # [H, 360] indexed by lon 0..359
        shift = int(round(self.center_lon)) - 180
        g = np.roll(g, -shift, axis=1)
        k0 = int(round(180 - self.span / 2))
        g = g[:, k0:k0 + int(self.span)]
        a = np.clip(g / 60.0, 0, 1) ** 0.8
        H, W = g.shape
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        rgba[..., 3] = (a * 200).astype(np.uint8)
        rgba[..., 0] = (c.blue() * a * 200 / 255).astype(np.uint8)
        rgba[..., 1] = (c.green() * a * 200 / 255).astype(np.uint8)
        rgba[..., 2] = (c.red() * a * 200 / 255).astype(np.uint8)
        return QImage(rgba.tobytes(), W, H, W * 4, QImage.Format.Format_ARGB32_Premultiplied).copy()

    # ---- painting -----------------------------------------------------------------
    def resizeEvent(self, e):
        self._bg = None
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        t = self.t
        f = self._frame()
        p.drawPixmap(0, 0, self._background(f))
        p.save()
        p.setClipRect(f)
        heat = self._heat_image()
        if heat is not None:
            p.drawImage(f, heat)
        if self.night:
            p.drawImage(f, self._night_image(time.time()))
        for pts, color, width, dashed in self.paths:
            self._draw_line(p, f, pts, color, width, dashed)
        p.restore()
        for lat, lon, color, label, size in self.markers:
            if not (self.lat_lo <= lat <= self.lat_hi):
                continue
            c = self.to_px(lat, lon, f)
            paint_glow_dot(p, c, px(size), color, True, t.led_off)
            if label:
                p.setFont(font(px(11), bold=True))
                p.setPen(qc("#000000", 180))
                p.drawText(QPointF(c.x() + px(size) * 0.6 + 1, c.y() + px(4) + 1), label)
                p.setPen(qc(color))
                p.drawText(QPointF(c.x() + px(size) * 0.6, c.y() + px(4)), label)
        if self.caption:
            p.setFont(font(px(11.5), bold=True))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(f.left() + px(8), f.bottom() - px(20), f.width() - px(16), px(18)),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)

    def _draw_line(self, p, f, pts, color, width, dashed):
        if len(pts) < 2:
            return
        segs, cur, prev_x = [], [], None
        for lat, lon in pts:
            x = self.xlon(lon)
            if prev_x is not None and abs(x - prev_x) > 180:
                segs.append(cur)
                cur = []
            cur.append(self.to_px(lat, lon, f))
            prev_x = x
        segs.append(cur)
        for glow, alpha, w in ((True, 60, width * 3), (False, 230, width)):
            pen = QPen(qc(color, alpha), px(w), Qt.PenStyle.DashLine if dashed and not glow else Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            for seg in segs:
                if len(seg) > 1:
                    path = QPainterPath(seg[0])
                    for q in seg[1:]:
                        path.lineTo(q)
                    p.drawPath(path)

    def mousePressEvent(self, e):
        f = self._frame()
        pos = e.position()
        if f.contains(pos):
            lon = (pos.x() - f.left()) / f.width() * self.span - self.span / 2 + self.center_lon
            lat = self.lat_hi - (pos.y() - f.top()) / f.height() * (self.lat_hi - self.lat_lo)
            self.clicked.emit(lat, (lon + 540) % 360 - 180)
