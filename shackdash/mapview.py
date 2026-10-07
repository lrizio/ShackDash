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
from .tiles import ATTRIBUTION, MAX_Z, tile_lat, tile_lon, tile_x, tile_y
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
        self.zoomable = False                # wheel zoom, drag pan, double-click back to the home view
        self._home: tuple | None = None
        self._drag = None
        self._tiles = None                   # optional TileLayer: detailed web-map background

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

    def set_tiles(self, layer):
        if self._tiles is not None:
            try:
                self._tiles.changed.disconnect(self.update)
            except (RuntimeError, TypeError):
                pass
        self._tiles = layer
        if layer is not None:
            layer.changed.connect(self.update)
        self.update()

    def _paint_tiles(self, p, f):
        ppd = f.width() / self.span
        z = max(1, min(MAX_Z, round(math.log2(max(1e-6, ppd * 360 / 256)))))
        lon_w, lon_e = self.center_lon - self.span / 2, self.center_lon + self.span / 2
        x0, x1 = math.floor(tile_x(lon_w, z)), math.floor(tile_x(lon_e, z))
        y0, y1 = math.floor(tile_y(self.lat_hi, z)), math.floor(tile_y(self.lat_lo, z))
        n = 1 << z
        if (x1 - x0 + 1) * (y1 - y0 + 1) > 120:
            return False
        for ty in range(max(0, y0), min(n - 1, y1) + 1):
            top, bot = tile_lat(ty, z), tile_lat(ty + 1, z)
            for tx in range(x0, x1 + 1):
                pm = self._tiles.get(z, tx % n, ty)
                if pm is None:
                    continue
                left = tile_lon(tx, z) - self.center_lon
                right = tile_lon(tx + 1, z) - self.center_lon
                ax = f.left() + (left + self.span / 2) / self.span * f.width()
                bx = f.left() + (right + self.span / 2) / self.span * f.width()
                ay = self.to_px(top, 0, f).y()
                by = self.to_px(bot, 0, f).y()
                p.drawPixmap(QRectF(ax, ay, bx - ax, by - ay), pm, QRectF(pm.rect()))
        return True

    # ---- zoom / pan ---------------------------------------------------------------
    def set_home(self):
        """Remember the current view as the one a double-click returns to."""
        self._home = (self.lat_lo, self.lat_hi, self.span, self.center_lon)

    def reset_view(self):
        if self._home:
            self.lat_lo, self.lat_hi, self.span, self.center_lon = self._home
            self._view_changed()

    def _view_changed(self):
        self._land_path = None
        self._bg = None
        self._night_key = None
        self.update()

    def _zoom_at(self, pos, k: float):
        """Scale the view by k (<1 zooms in), keeping the point under pos fixed."""
        f = self._frame()
        fx = min(1.0, max(0.0, (pos.x() - f.left()) / f.width()))
        fy = min(1.0, max(0.0, (pos.y() - f.top()) / f.height()))
        h = self._home or (self.lat_lo, self.lat_hi, self.span, self.center_lon)
        home_span = h[2]
        new_span = min(min(360.0, home_span * 4), max(home_span / 300, self.span * k))
        k = new_span / self.span
        rng = (self.lat_hi - self.lat_lo) * k
        lon_at = self.center_lon + (fx - 0.5) * self.span
        lat_at = self.lat_hi - fy * (self.lat_hi - self.lat_lo)
        hi = lat_at + fy * rng
        hi = min(90.0, max(-90.0 + rng, hi)) if rng < 180 else 90.0
        self.lat_hi, self.lat_lo = hi, hi - rng
        self.span = new_span
        self.center_lon = (lon_at - (fx - 0.5) * new_span + 540) % 360 - 180
        self._view_changed()

    def _pan(self, dx_px: float, dy_px: float):
        f = self._frame()
        rng = self.lat_hi - self.lat_lo
        dlon = -dx_px / f.width() * self.span
        dlat = dy_px / f.height() * rng
        hi = min(90.0, max(-90.0 + rng, self.lat_hi + dlat))
        self.lat_hi, self.lat_lo = hi, hi - rng
        self.center_lon = (self.center_lon + dlon + 540) % 360 - 180
        self._view_changed()

    def wheelEvent(self, e):
        if not self.zoomable:
            return super().wheelEvent(e)
        steps = e.angleDelta().y() / 120.0
        if steps:
            self._zoom_at(e.position(), 0.8 ** steps)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if self.zoomable:
            self.reset_view()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            pos = e.position()
            last, moved = self._drag
            if moved or (pos - last).manhattanLength() > 4:
                self._pan(pos.x() - last.x(), pos.y() - last.y())
                self._drag = (pos, True)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, e):
        moved = self._drag is not None and self._drag[1]
        self._drag = None
        self.unsetCursor()
        if not moved:
            self._emit_click(e.position())

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
        step = next((g for g in (30, 10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05) if self.span / g >= 4), 0.05)
        la = math.ceil(self.lat_lo / step) * step
        while la < self.lat_hi:
            y = self.to_px(la, 0, f).y()
            p.drawLine(QPointF(f.left(), y), QPointF(f.right(), y))
            la += step
        lo = math.floor((self.center_lon - self.span / 2) / step) * step
        while lo <= self.center_lon + self.span / 2:
            x = self.to_px(0, lo, f).x()
            p.drawLine(QPointF(x, f.top()), QPointF(x, f.bottom()))
            lo += step
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
        shown = False
        if self._tiles is not None:
            shown = self._paint_tiles(p, f)
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
            if not f.adjusted(-px(4), -px(4), px(4), px(4)).contains(c):
                continue
            paint_glow_dot(p, c, px(size), color, True, t.led_off)
            if label:
                p.setFont(font(px(11), bold=True))
                p.setPen(qc("#000000", 180))
                p.drawText(QPointF(c.x() + px(size) * 0.6 + 1, c.y() + px(4) + 1), label)
                p.setPen(qc(color))
                p.drawText(QPointF(c.x() + px(size) * 0.6, c.y() + px(4)), label)
        if shown:
            p.setFont(font(px(9)))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(f.left() + px(8), f.bottom() - px(16), f.width() - px(16), px(14)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, ATTRIBUTION)
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
        if self.zoomable:
            self._drag = (e.position(), False)
        else:
            self._emit_click(e.position())

    def _emit_click(self, pos):
        f = self._frame()
        if f.contains(pos):
            lon = (pos.x() - f.left()) / f.width() * self.span - self.span / 2 + self.center_lon
            lat = self.lat_hi - (pos.y() - f.top()) / f.height() * (self.lat_hi - self.lat_lo)
            self.clicked.emit(lat, (lon + 540) % 360 - 180)
