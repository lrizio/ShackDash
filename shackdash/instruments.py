"""Dashboard instruments in the family 3D look: glowing stat tiles, trend
plots, a bar chart, a heat grid and recessed-screen tables."""
from __future__ import annotations

import calendar
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QWidget)

from .theme import Theme, px, shade
from .widgets import font, paint_glow_dot, paint_recess, qc

SMOOTH = "Bahnschrift"


def smooth_font(size_px: float, weight=QFont.Weight.DemiBold) -> QFont:
    f = QFont(SMOOTH)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setPixelSize(max(6, round(size_px)))
    f.setWeight(weight)
    return f


def paint_glow_text(p: QPainter, rect: QRectF, text: str, fnt: QFont, color: str,
                    align=Qt.AlignmentFlag.AlignCenter, glow: bool = True) -> None:
    """LED-style readout: soft halo stroke under a solid fill (smooth font, never 7-segment)."""
    fm = QFontMetricsF(fnt)
    w = fm.horizontalAdvance(text)
    if align & Qt.AlignmentFlag.AlignLeft:
        x = rect.left()
    elif align & Qt.AlignmentFlag.AlignRight:
        x = rect.right() - w
    else:
        x = rect.left() + (rect.width() - w) / 2
    base = rect.top() + (rect.height() + fm.capHeight()) / 2
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    path.addText(QPointF(x, base), fnt, text)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if glow:
        for width, alpha in ((fnt.pixelSize() * 0.22, 26), (fnt.pixelSize() * 0.11, 50)):
            p.setPen(QPen(qc(color, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qc(color))
    p.drawPath(path)
    p.restore()


def fit_font(text: str, width: float, size: float) -> QFont:
    fnt = smooth_font(size)
    while QFontMetricsF(fnt).horizontalAdvance(text) > width and size > 8:
        size *= 0.92
        fnt = smooth_font(size)
    return fnt


class StatTile(QWidget):
    """A recessed readout tile: caption + status LED on top, big glowing value,
    small sub-line underneath."""

    def __init__(self, theme: Theme, caption: str, unit: str = "", parent=None, max_px: float = 44):
        super().__init__(parent)
        self.t = theme
        self.caption = caption
        self.unit = unit
        self.max_px = max_px
        self.value = "--"
        self.sub = ""
        self.color = theme.dim
        self.led: str | None = None
        self.setMinimumSize(px(110), px(86))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set(self, value: str, color: str | None = None, sub: str = "", led: str | None = None, tip: str | None = None):
        new = (value, color or self.t.teal_edge, sub, led)
        if new != (self.value, self.color, self.sub, self.led):
            self.value, self.color, self.sub, self.led = new
            self.update()
        if tip is not None:
            self.setToolTip(tip)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        h = r.height()
        cap_h = min(px(20), max(px(15), h * 0.2))
        d = cap_h * 0.6
        paint_glow_dot(p, QPointF(r.left() + px(8) + d / 2, r.top() + px(5) + cap_h / 2), d,
                       self.led or t.main, self.led is not None, t.led_off)
        p.setFont(font(min(px(12), cap_h * 0.64), bold=True))
        p.setPen(qc(t.dim))
        p.drawText(QRectF(r.left() + px(12) + d, r.top() + px(5), r.width() - d - px(18), cap_h),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.caption)
        sub_h = cap_h if self.sub else px(4)
        body = QRectF(r.left() + px(8), r.top() + px(5) + cap_h, r.width() - px(16), h - cap_h - sub_h - px(8))
        text = self.value + (f" {self.unit}" if self.unit and self.value not in ("--", "") else "")
        fnt = fit_font(text, body.width(), min(body.height() * 0.8, px(self.max_px)))
        paint_glow_text(p, body, text, fnt, self.color)
        if self.sub:
            p.setFont(font(min(px(12), cap_h * 0.64)))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(r.left() + px(6), r.bottom() - sub_h - px(4), r.width() - px(12), sub_h),
                       Qt.AlignmentFlag.AlignCenter, self.sub)


class TrendPlot(QWidget):
    """Time-series trace on a recessed screen: glowing line(s), optional log
    axis, labelled reference levels, x axis = the last N hours (UTC ticks)."""

    def __init__(self, theme: Theme, unit: str = "", log: bool = False, ymin=None, ymax=None,
                 hours: float = 24, parent=None):
        super().__init__(parent)
        self.t = theme
        self.unit = unit
        self.log = log
        self.ymin, self.ymax = ymin, ymax
        self.hours = hours
        self.future_h = 0.0
        self.series: list[tuple[list, list, str, str]] = []
        self.levels: list[tuple[float, str, str]] = []
        self.shade_below_zero: str | None = None
        self.message = "waiting for data"
        self.setMinimumSize(px(200), px(110))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_series(self, series, message: str = ""):
        self.series = series
        self.message = message
        self.update()

    def _y(self, v, lo, hi, top, bottom):
        if self.log:
            v, lo, hi = (math.log10(max(x, 1e-12)) for x in (v, lo, hi))
        if hi == lo:
            hi = lo + 1
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        left, right = r.left() + px(46), r.right() - px(12)
        top, bottom = r.top() + px(22), r.bottom() - px(20)
        now = time.time()
        t0 = now - self.hours * 3600
        t1 = now + self.future_h * 3600
        vals = [v for s in self.series for tt, v in zip(s[0], s[1])
                if v is not None and t0 <= tt <= t1 and (not self.log or v > 0)]
        if not vals:
            p.setPen(qc(t.faint))
            p.setFont(font(px(13)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message or "no data")
            return
        lo = self.ymin if self.ymin is not None else min(vals)
        hi = self.ymax if self.ymax is not None else max(vals)
        if self.ymin is None and self.ymax is None and not self.log:
            pad = (hi - lo) * 0.1 or 1
            lo, hi = lo - pad, hi + pad
        if max(vals) > hi:
            hi = max(vals) * (1.5 if self.log else 1.08)
        if min(vals) < lo:
            lo = min(vals) * (0.6 if self.log else 1.08) if min(vals) > 0 or self.log else min(vals) * 1.08
        p.setFont(font(px(10.5)))
        grid = qc(shade(t.screen, 26))
        if self.log:
            e0, e1 = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
            ticks = [10.0 ** e for e in range(e0, e1 + 1)]
            lo, hi = 10.0 ** e0, 10.0 ** e1
        else:
            span = hi - lo
            step = 10 ** math.floor(math.log10(span / 4)) if span > 0 else 1
            for m in (1, 2, 2.5, 5, 10):
                if span / (step * m) <= 6:
                    step *= m
                    break
            first = math.ceil(lo / step) * step
            ticks = [first + i * step for i in range(0, 14) if first + i * step <= hi]
        for v in ticks:
            y = self._y(v, lo, hi, top, bottom)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(left, y), QPointF(right, y))
            p.setPen(qc(t.dim))
            lab = f"1e{round(math.log10(v))}" if self.log else f"{v:g}"
            p.drawText(QRectF(r.left() + px(2), y - px(8), px(40), px(16)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, lab)
        xs = lambda tt: left + (tt - t0) / (t1 - t0) * (right - left)
        total_h = self.hours + self.future_h
        step_h = 3 if total_h <= 26 else 6 if total_h <= 50 else 12 if total_h <= 80 else 24
        hr = math.floor(t1 / 3600)
        for k in range(0, int(total_h) + 2):
            tt = (hr - k) * 3600
            if tt < t0 or (hr - k) % step_h:
                continue
            x = xs(tt)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(x - px(24), bottom + px(2), px(48), px(16)), Qt.AlignmentFlag.AlignCenter,
                       time.strftime("%H", time.gmtime(tt)) + "z")
        if self.future_h:
            x = xs(now)
            p.setPen(QPen(qc(t.amber, 170), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
        for v, lab, col in self.levels:
            if lo <= v <= hi:
                y = self._y(v, lo, hi, top, bottom)
                p.setPen(QPen(qc(col, 140), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(left, y), QPointF(right, y))
                p.setPen(qc(col))
                p.drawText(QRectF(right - px(40), y - px(15), px(38), px(14)), Qt.AlignmentFlag.AlignRight, lab)
        p.save()
        p.setClipRect(QRectF(left, top - 2, right - left, bottom - top + 4))
        if self.shade_below_zero and lo < 0 < hi:
            y0 = self._y(0, lo, hi, top, bottom)
            p.fillRect(QRectF(left, y0, right - left, bottom - y0), qc(self.shade_below_zero, 22))
            p.setPen(QPen(qc(t.dim, 160), 1))
            p.drawLine(QPointF(left, y0), QPointF(right, y0))
        for ts, vs, color, _label in self.series:
            path = QPainterPath()
            started, last_t = False, None
            gap = max(1800.0, 2.5 * (ts[1] - ts[0])) if len(ts) > 1 else 1800.0
            for tt, v in zip(ts, vs):
                if v is None or tt < t0 or tt > t1 or (self.log and v <= 0):
                    started = False
                    continue
                x, y = xs(tt), self._y(v, lo, hi, top, bottom)
                if not started or (last_t is not None and tt - last_t > gap):
                    path.moveTo(x, y)
                    started = True
                else:
                    path.lineTo(x, y)
                last_t = tt
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qc(color, 55), px(4.5), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(qc(color), px(1.6)))
            p.drawPath(path)
        p.restore()
        x = left + px(4)
        p.setFont(font(px(11.5), bold=True))
        for ts, vs, color, label in self.series:
            last = next((v for tt, v in zip(reversed(ts), reversed(vs)) if v is not None and tt <= now), None)
            if last is None or not label:
                continue
            txt = f"{label} {last:.2e}" if self.log else f"{label} {last:.3g}{(' ' + self.unit) if self.unit else ''}"
            p.setPen(qc(color))
            p.drawText(QRectF(x, r.top() + px(3), px(300), px(18)), Qt.AlignmentFlag.AlignLeft, txt)
            x += p.fontMetrics().horizontalAdvance(txt) + px(16)


class DatePlot(QWidget):
    """Series over an arbitrary date range (days to decades): glowing lines,
    an optional shaded band (e.g. a forecast's low/high), a 'now' marker and
    year / month / day ticks chosen from the span."""

    def __init__(self, theme: Theme, unit: str = "", ymin=None, parent=None):
        super().__init__(parent)
        self.t = theme
        self.unit = unit
        self.ymin = ymin
        self.series: list[tuple] = []          # (xs, ys, color, label, dashed)
        self.bands: list[tuple] = []           # (xs, lows, highs, color)
        self.x_range: tuple[float, float] | None = None
        self.message = "waiting for data"
        self.setMinimumSize(px(200), px(110))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, series, bands=(), x_range=None, message=""):
        self.series, self.bands, self.x_range, self.message = list(series), list(bands), x_range, message
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        pts = [(x, y) for s in self.series for x, y in zip(s[0], s[1]) if y is not None]
        pts += [(x, y) for b in self.bands for x, lo, hi in zip(b[0], b[1], b[2]) for y in (lo, hi) if y is not None]
        if not pts:
            p.setPen(qc(t.faint))
            p.setFont(font(px(13)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message or "no data")
            return
        x0, x1 = self.x_range or (min(x for x, _ in pts), max(x for x, _ in pts))
        vals = [y for x, y in pts if x0 <= x <= x1] or [0, 1]
        lo = self.ymin if self.ymin is not None else min(vals)
        hi = max(vals)
        pad = (hi - lo) * 0.08 or 1
        hi += pad
        if self.ymin is None:
            lo -= pad
        left, right = r.left() + px(46), r.right() - px(12)
        top, bottom = r.top() + px(22), r.bottom() - px(20)
        xs = lambda x: left + (x - x0) / ((x1 - x0) or 1) * (right - left)
        ys = lambda v: bottom - (v - lo) / ((hi - lo) or 1) * (bottom - top)
        grid = qc(shade(t.screen, 26))
        p.setFont(font(px(10.5)))
        span = hi - lo
        step = 10 ** math.floor(math.log10(span / 4)) if span > 0 else 1
        for m in (1, 2, 2.5, 5, 10):
            if span / (step * m) <= 6:
                step *= m
                break
        v = math.ceil(lo / step) * step
        while v <= hi:
            y = ys(v)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(left, y), QPointF(right, y))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(r.left() + px(2), y - px(8), px(40), px(16)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:g}")
            v += step
        days = (x1 - x0) / 86400
        g0 = time.gmtime(x0)
        ticks = []
        if days > 1500:                                            # years
            every = 2 if days < 6000 else 5
            for yr in range(g0.tm_year, time.gmtime(x1).tm_year + 2):
                if yr % every == 0:
                    ticks.append((calendar_ts(yr, 1, 1), str(yr)))
        elif days > 120:                                           # months
            y_, m_ = g0.tm_year, g0.tm_mon
            while True:
                ts = calendar_ts(y_, m_, 1)
                if ts > x1:
                    break
                ticks.append((ts, time.strftime("%b" if m_ != 1 else "%b %Y", time.gmtime(ts))))
                m_ += 1
                if m_ > 12:
                    y_, m_ = y_ + 1, 1
        else:                                                      # days
            every = 1 if days <= 10 else 2 if days <= 20 else 4 if days <= 40 else 7
            d0 = x0 - x0 % 86400
            for k in range(int(days) + 2):
                ts = d0 + k * 86400
                if k % every == 0:
                    ticks.append((ts, time.strftime("%d %b", time.gmtime(ts))))
        for ts, lab in ticks:
            if not (x0 <= ts <= x1):
                continue
            x = xs(ts)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(x - px(34), bottom + px(2), px(68), px(16)), Qt.AlignmentFlag.AlignCenter, lab)
        now = time.time()
        if x0 < now < x1:
            p.setPen(QPen(qc(t.amber, 170), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xs(now), top), QPointF(xs(now), bottom))
        p.save()
        p.setClipRect(QRectF(left, top - 2, right - left, bottom - top + 4))
        for bx, blo, bhi, color in self.bands:
            keep = [(x, a, b) for x, a, b in zip(bx, blo, bhi) if a is not None and b is not None]
            if len(keep) > 1:
                path = QPainterPath(QPointF(xs(keep[0][0]), ys(keep[0][2])))
                for x, _a, b in keep[1:]:
                    path.lineTo(xs(x), ys(b))
                for x, a, _b in reversed(keep):
                    path.lineTo(xs(x), ys(a))
                path.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qc(color, 45))
                p.drawPath(path)
        for sx, sy, color, _label, dashed in self.series:
            path = QPainterPath()
            started = False
            for x, y in zip(sx, sy):
                if y is None:
                    started = False
                    continue
                if not started:
                    path.moveTo(xs(x), ys(y))
                    started = True
                else:
                    path.lineTo(xs(x), ys(y))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if not dashed:
                p.setPen(QPen(qc(color, 55), px(4.5), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.drawPath(path)
            p.setPen(QPen(qc(color), px(1.6), Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            p.drawPath(path)
        p.restore()
        x = left + px(4)
        p.setFont(font(px(11.5), bold=True))
        for _sx, _sy, color, label, _d in self.series:
            if label:
                p.setPen(qc(color))
                p.drawText(QRectF(x, r.top() + px(3), px(400), px(18)), Qt.AlignmentFlag.AlignLeft, label)
                x += p.fontMetrics().horizontalAdvance(label) + px(16)


def calendar_ts(y: int, m: int, d: int) -> float:
    return calendar.timegm((y, m, d, 0, 0, 0))


class BarPlot(QWidget):
    """Coloured bars on a recessed screen (the 3-hourly Kp chart)."""

    def __init__(self, theme: Theme, ymax: float = 9, right_labels=None, parent=None):
        super().__init__(parent)
        self.t = theme
        self.ymax = ymax
        self.right_labels = right_labels or {}
        self.bars: list[tuple[float, float, str, bool]] = []    # (epoch, value, colour, predicted)
        self.label_every = 1                                     # day labels on every Nth day
        self.setMinimumSize(px(200), px(110))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_bars(self, bars):
        self.bars = bars
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        left, right = r.left() + px(30), r.right() - px(32)
        top, bottom = r.top() + px(12), r.bottom() - px(20)
        p.setFont(font(px(10.5)))
        for v in range(0, int(self.ymax) + 1):
            y = bottom - v / self.ymax * (bottom - top)
            p.setPen(QPen(qc(shade(t.screen, 26)), 1))
            p.drawLine(QPointF(left, y), QPointF(right, y))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(r.left(), y - px(8), px(24), px(16)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(v))
            if v in self.right_labels:
                p.drawText(QRectF(right + px(3), y - px(8), px(30), px(16)),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.right_labels[v])
        if not self.bars:
            p.setPen(qc(t.faint))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "waiting for data")
            return
        bw = (right - left) / len(self.bars)
        last_day = None
        for i, (ts, v, col, pred) in enumerate(self.bars):
            x = left + i * bw
            h = max(1.0, v / self.ymax * (bottom - top))
            body = QRectF(x + bw * 0.12, bottom - h, bw * 0.76, h)
            g = QLinearGradient(body.topLeft(), body.topRight())
            g.setColorAt(0, qc(shade(col, 40), 110 if pred else 255))
            g.setColorAt(1, qc(shade(col, -30), 110 if pred else 255))
            p.setPen(QPen(qc(col, 110 if pred else 200), 1, Qt.PenStyle.DashLine if pred else Qt.PenStyle.SolidLine))
            p.setBrush(g)
            p.drawRoundedRect(body, px(2), px(2))
            day = time.strftime("%d %b", time.gmtime(ts))
            if day != last_day:
                last_day = day
                n_day = int(ts // 86400)
                if n_day % self.label_every:
                    continue
                if i == 0 and ts % 86400 >= 3600:       # partial first day: no label, it would collide
                    continue
                p.setPen(QPen(qc(shade(t.screen, 40)), 1))
                p.drawLine(QPointF(x, top), QPointF(x, bottom))
                p.setPen(qc(t.dim))
                p.drawText(QRectF(x + px(2), bottom + px(2), px(60), px(16)), Qt.AlignmentFlag.AlignLeft, day)


class HeatGrid(QWidget):
    """Rows x columns of glowing cells (band activity over time)."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.t = theme
        self.rows: list[str] = []
        self.cols: list[str] = []
        self.values: list[list[float]] = []
        self.message = "waiting for data"
        self.setMinimumSize(px(240), px(150))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, rows, cols, values, message=""):
        self.rows, self.cols, self.values, self.message = rows, cols, values, message
        self.update()

    def color_for(self, f: float) -> QColor:
        t = self.t
        stops = [(0.0, shade(t.screen, 14)), (0.15, t.teal), (0.45, t.main), (0.75, t.amber), (1.0, t.red)]
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if f <= b:
                k = (f - a) / (b - a) if b > a else 0
                A, B = QColor(ca), QColor(cb)
                return QColor(round(A.red() + (B.red() - A.red()) * k), round(A.green() + (B.green() - A.green()) * k),
                              round(A.blue() + (B.blue() - A.blue()) * k))
        return QColor(t.red)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        if not self.rows or not any(any(row) for row in self.values):
            p.setPen(qc(t.faint))
            p.setFont(font(px(13)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message or "no activity")
            return
        left, top = r.left() + px(48), r.top() + px(10)
        right, bottom = r.right() - px(10), r.bottom() - px(20)
        cw = (right - left) / max(1, len(self.cols))
        ch = (bottom - top) / max(1, len(self.rows))
        vmax = max(max(row) for row in self.values) or 1
        p.setFont(font(min(px(11.5), ch * 0.7), bold=True))
        for i, name in enumerate(self.rows):
            y = top + i * ch
            p.setPen(qc(t.dim))
            p.drawText(QRectF(r.left(), y, px(42), ch), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, name)
            for j, v in enumerate(self.values[i]):
                cell = QRectF(left + j * cw + 1.5, y + 1.5, cw - 3, ch - 3)
                f = math.sqrt(v / vmax) if v else 0
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.color_for(f))
                p.drawRoundedRect(cell, px(3), px(3))
                if v and ch > px(13) and cw > px(22):
                    p.setPen(qc("#ffffff" if f > 0.3 else t.dim))
                    p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(int(v)))
        p.setPen(qc(t.dim))
        p.setFont(font(px(10.5)))
        for j, name in enumerate(self.cols):
            p.drawText(QRectF(left + j * cw, bottom + px(2), cw, px(16)), Qt.AlignmentFlag.AlignCenter, name)


def make_table(headers: list[str], widths: dict | None = None, stretch_col: int | None = None) -> QTableWidget:
    """A read-only, row-selecting table styled as a recessed screen."""
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels(headers)
    tb.verticalHeader().setVisible(False)
    tb.verticalHeader().setDefaultSectionSize(px(22))
    tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tb.setAlternatingRowColors(True)
    tb.setShowGrid(False)
    tb.setWordWrap(False)
    tb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    tb.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tb.setTextElideMode(Qt.TextElideMode.ElideRight)
    h = tb.horizontalHeader()
    h.setHighlightSections(False)
    h.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for c, w in (widths or {}).items():
        tb.setColumnWidth(c, px(w))
    if stretch_col is not None:
        h.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    else:
        h.setStretchLastSection(True)
    return tb


def fill_table(tb: QTableWidget, rows, colors=None, right: set | None = None, tips=None, data=None):
    """rows: list of tuples of cell text; colors: per-row colour or None. Keeps the scroll position."""
    sb = tb.verticalScrollBar().value()
    tb.setUpdatesEnabled(False)
    tb.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j in range(tb.columnCount()):
            val = row[j] if j < len(row) else ""
            it = tb.item(i, j)
            if it is None:
                it = QTableWidgetItem()
                tb.setItem(i, j, it)
            it.setText("" if val is None else str(val))
            if right and j in right:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            col = colors[i] if colors else None
            if col:
                it.setForeground(QColor(col))
            else:                                   # no colour: follow the theme (even if not polished yet)
                it.setData(Qt.ItemDataRole.ForegroundRole, None)
            it.setToolTip(tips[i] if tips and tips[i] else "")
            if data is not None and j == 0:
                it.setData(Qt.ItemDataRole.UserRole, data[i])
    tb.setUpdatesEnabled(True)
    tb.verticalScrollBar().setValue(sb)
