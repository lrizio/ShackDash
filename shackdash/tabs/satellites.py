"""D · SATELLITES: passes, live tracking with Doppler, ISS, SatNOGS"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QWidget

from .. import sats as S
from ..instruments import StatTile, fill_table, make_table
from ..mapview import MapView
from ..theme import px, shade
from ..widgets import font, paint_glow_dot, paint_recess, qc
from .base import Tab, ago, hline_search, note, panel, stretch


def footprint(lat, lon, alt_km, n=72):
    lam = math.acos(S.A_E / (S.A_E + max(alt_km, 1)))
    la, lo = math.radians(lat), math.radians(lon)
    pts = []
    for i in range(n + 1):
        b = 2 * math.pi * i / n
        la2 = math.asin(math.sin(la) * math.cos(lam) + math.cos(la) * math.sin(lam) * math.cos(b))
        lo2 = lo + math.atan2(math.sin(b) * math.sin(lam) * math.cos(la), math.cos(lam) - math.sin(la) * math.sin(la2))
        pts.append((math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180))
    return pts


class SkyPlot(QWidget):
    def __init__(self, t):
        super().__init__()
        self.t = t
        self.track = None            # (ts, az, el)
        self.now_pos = None          # (az, el)
        self.label = ""
        self.setMinimumSize(px(200), px(200))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set(self, track, now_pos, label):
        self.track, self.now_pos, self.label = track, now_pos, label
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        R = min(r.width(), r.height()) / 2 - px(24)
        c = r.center()

        def xy(az, el):
            rr = R * (90 - max(0.0, el)) / 90
            a = math.radians(az)
            return QPointF(c.x() + rr * math.sin(a), c.y() - rr * math.cos(a))
        p.setFont(font(px(11), bold=True))
        for el in (0, 30, 60):
            rr = R * (90 - el) / 90
            p.setPen(QPen(qc(shade(t.screen, 40 if el == 0 else 26)), 1.2 if el == 0 else 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, rr, rr)
            if el:
                p.setPen(qc(t.faint))
                p.drawText(QPointF(c.x() + 3, c.y() - rr + px(12)), f"{el}°")
        for az, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            p.setPen(QPen(qc(shade(t.screen, 26)), 1))
            p.drawLine(c, xy(az, 0))
            q = xy(az, -12)
            a = math.radians(az)
            q = QPointF(c.x() + (R + px(13)) * math.sin(a), c.y() - (R + px(13)) * math.cos(a))
            p.setPen(qc(t.dim))
            p.drawText(QRectF(q.x() - px(10), q.y() - px(8), px(20), px(16)), Qt.AlignmentFlag.AlignCenter, lab)
        if self.track is not None:
            ts, az, el = self.track
            path = QPainterPath()
            first = True
            for a, e in zip(az, el):
                if e < 0:
                    continue
                q = xy(a, e)
                if first:
                    path.moveTo(q)
                    first = False
                else:
                    path.lineTo(q)
            p.setPen(QPen(qc(t.sub, 60), px(5), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
            p.setPen(QPen(qc(t.sub), px(1.8)))
            p.drawPath(path)
            vis = [(a, e) for a, e in zip(az, el) if e >= 0]
            if vis:
                p.setFont(font(px(11), bold=True))
                for (a, e), lab, col in ((vis[0], "AOS", t.main), (vis[-1], "LOS", t.red)):
                    q = xy(a, e)
                    paint_glow_dot(p, q, px(10), col, True, t.led_off)
                    p.setPen(qc(col))
                    p.drawText(QPointF(q.x() + px(7), q.y() - px(5)), lab)
        if self.now_pos and self.now_pos[1] > 0:
            paint_glow_dot(p, xy(*self.now_pos), px(18), t.amber, True, t.led_off)
        p.setPen(qc(t.dim))
        p.setFont(font(px(11.5), bold=True))
        p.drawText(QRectF(r.left() + px(10), r.bottom() - px(24), r.width() - px(20), px(18)),
                   Qt.AlignmentFlag.AlignLeft, self.label)


class SatTab(Tab):
    title = "D · SATELLITES"
    keys = ("tle", "sat_tx", "satnogs_obs", "land")
    footer = "Orbits: CelesTrak TLEs, SGP4 computed locally · transmitters and observations: SatNOGS (Libre Space Foundation)"

    def build(self):
        t = self.t
        self.sats: list[dict] = []
        self.by_norad: dict[int, dict] = {}
        self.passes: list[dict] = []
        self.sel_norad: int | None = None
        self.sel_pass: dict | None = None
        self.search = ""
        self._computing = False
        self._last_calc = 0.0
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.pass_tb = make_table(["AOS", "SATELLITE", "MAX", "AZ", "MIN", "STARTS"],
                                  {0: 76, 1: 128, 2: 38, 3: 66, 4: 34}, stretch_col=5)
        self.pass_tb.itemSelectionChanged.connect(self._pick_pass)
        self.pass_note = note("")
        g.addWidget(panel(t, "PASSES OVER MY QTH  ·  NEXT 24 h",
                          [hline_search("filter satellites (e.g. ISS, SO-50, RS-44)", self._set_search),
                           self.pass_tb, self.pass_note], dot=t.main), 0, 0, 2, 1)
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        self.tile = {}
        for k, cap in (("az", "AZIMUTH"), ("el", "ELEVATION"), ("rng", "RANGE"), ("rr", "RANGE RATE")):
            self.tile[k] = StatTile(t, cap)
            tiles.addWidget(self.tile[k])
        self.tx_tb = make_table(["TRANSMITTER", "MODE", "DOWN", "RX NOW", "UP", "TX NOW"],
                                {0: 128, 1: 46, 2: 70, 3: 70, 4: 70}, stretch_col=5)
        self.track_fs = panel(t, "TRACKING", [tiles, self.tx_tb], dot=t.amber)
        g.addWidget(self.track_fs, 0, 1)
        self.sky = SkyPlot(t)
        g.addWidget(panel(t, "SKY VIEW  ·  SELECTED PASS", self.sky, dot=t.sub), 1, 1)
        self.map = MapView(t, center_lon=self.ctx.qth[1])
        g.addWidget(panel(t, "GROUND TRACK  ·  ISS + SELECTED", self.map, dot=t.teal_edge), 0, 2)
        self.obs_tb = make_table(["UTC", "SATELLITE", "STATION", "MODE"], {0: 46, 1: 140, 2: 170}, stretch_col=3)
        g.addWidget(panel(t, "SATNOGS  ·  LATEST GOOD OBSERVATIONS", self.obs_tb, dot=t.purple), 1, 2)
        g.setColumnStretch(0, 30)
        g.setColumnStretch(1, 34)
        g.setColumnStretch(2, 36)
        g.setRowStretch(0, 1)
        g.setRowStretch(1, 1)

    # ---- data ------------------------------------------------------------------------
    def on_data(self, key, d):
        if key == "tle":
            self.sats = d
            self.by_norad = {s["norad"]: s for s in d}
            if self.sel_norad is None and 25544 in self.by_norad:
                self.sel_norad = 25544
            self._recalc()
        elif key == "land":
            self.map.set_land(d)
        elif key == "satnogs_obs":
            rows = []
            for o in d[:60]:
                s = self.by_norad.get(o["norad"])
                rows.append((time.strftime("%H:%M", time.gmtime(o["t"])), s["name"] if s else f"NORAD {o['norad']}",
                             o["station"], o["mode"]))
            fill_table(self.obs_tb, rows)
        elif key == "sat_tx":
            self._fill_tx()

    def qth_changed(self):
        self.map.set_center(self.ctx.qth[1])
        self._recalc()

    def _recalc(self):
        if not self.sats or self._computing:
            return
        self._computing = True
        self._last_calc = time.time()
        lat, lon = self.ctx.qth
        min_el = float(self.ctx.cfg.get("sat_min_el", 10))
        sats = list(self.sats)
        self.pass_note.setText("computing passes…")
        self.ctx.hub.run(lambda: S.find_passes(sats, lat, lon, min_el, time.time() - 900, 24.25),
                         self._got_passes)

    def _got_passes(self, passes, err):
        self._computing = False
        if err:
            self.pass_note.setText(f"pass prediction failed: {err}")
            return
        self.passes = [p for p in passes if p["los"] > time.time()]
        self._fill_passes()
        if self.sel_pass is None:
            nxt = next((p for p in self.passes if p["norad"] == self.sel_norad), None)
            if nxt:
                self._select(nxt)
        self.pass_note.setText(f"{len(self.passes)} passes above {self.ctx.cfg.get('sat_min_el', 10)}° from "
                               f"{len(self.sats)} amateur satellites · click a pass to track it")

    def _set_search(self, s):
        self.search = s.strip().upper()
        self._fill_passes()

    def _visible_passes(self):
        return [p for p in self.passes if not self.search or self.search in p["name"].upper()]

    def _fill_passes(self):
        now = time.time()
        rows, colors, data = [], [], []
        for p in self._visible_passes()[:300]:
            if p["los"] < now:
                continue
            live = p["aos"] <= now <= p["los"]
            starts = "NOW" if live else ("" + (f"{(p['aos'] - now) / 60:.0f}m" if p["aos"] - now < 5400
                                                  else f"{(p['aos'] - now) / 3600:.1f}h"))
            rows.append((time.strftime("%a %H:%M", time.localtime(p["aos"])), p["name"], f"{p['max_el']:.0f}°",
                         f"{p['aos_az']:.0f}→{p['los_az']:.0f}", f"{(p['los'] - p['aos']) / 60:.0f}", starts))
            colors.append(self.t.amber if live else self.t.main if p["max_el"] >= 45 else None)
            data.append(id(p))
        self._row_pass = {i: p for i, p in enumerate(q for q in self._visible_passes() if q["los"] >= now)}
        fill_table(self.pass_tb, rows, colors, right={2, 4})

    def _pick_pass(self):
        rows = self.pass_tb.selectionModel().selectedRows()
        if rows:
            p = self._row_pass.get(rows[0].row())
            if p:
                self._select(p)

    def _select(self, p):
        self.sel_pass = p
        self.sel_norad = p["norad"]
        sat = self.by_norad.get(p["norad"])
        if sat:
            lat, lon = self.ctx.qth
            self._track = S.track(sat, lat, lon, p["aos"] - 60, p["los"] + 60, 15)
        self.track_fs.set_title(f"TRACKING  ·  {p['name']}", dot=self.t.amber)
        self._fill_tx()
        self.tick()

    def _fill_tx(self):
        self._tx = (self.ctx.hub.data.get("sat_tx") or {}).get(self.sel_norad, [])
        self._draw_tx(None)

    def _draw_tx(self, rr):
        rows = []
        for x in self._tx:
            down, up = x["down"], x["up"]
            f = lambda hz: f"{hz / 1e6:.4f}" if hz else ""
            rx_now = f(down * (1 - rr / S.C_KMS)) if (down and rr is not None) else ""
            tx_now = f(up / (1 - rr / S.C_KMS)) if (up and rr is not None) else ""
            rows.append((x["desc"], x["mode"], f(down), rx_now, f(up), tx_now))
        if not rows:
            rows = [("no active amateur transmitters listed in SatNOGS" if self.ctx.hub.data.get("sat_tx") else
                     "loading transmitter list…", "", "", "", "", "")]
        fill_table(self.tx_tb, rows, right={2, 3, 4, 5})

    def tick(self):
        now = time.time()
        if self.sats and now - self._last_calc > 1800:
            self._recalc()
        t = self.t
        lat, lon = self.ctx.qth
        sat = self.by_norad.get(self.sel_norad) if self.sel_norad else None
        markers, paths = [], []
        iss = self.by_norad.get(25544)
        for s, col, name in ((iss, t.amber, "ISS"), (sat if sat is not iss else None, t.main, None)):
            if not s:
                continue
            st = S.now_state(s, lat, lon, now)
            if not st:
                continue
            paths.append((S.ground_track(s, now, 95), col, 1.2, True))
            paths.append((footprint(st["lat"], st["lon"], st["alt"]), col, 0.8, False))
            markers.append((st["lat"], st["lon"], col, name or s["name"][:14], 14))
        markers.append((lat, lon, t.sub, self.ctx.call or "QTH", 11))
        self.map.set_overlays(markers=markers, paths=paths,
                              caption="dashed = next orbit · ring = radio footprint (can hear the satellite)")
        if sat:
            st = S.now_state(sat, lat, lon, now)
            if st:
                up = st["el"] > 0
                self.tile["az"].set(f"{st['az']:.0f}°", t.amber if up else t.dim, "", led=t.amber if up else None)
                self.tile["el"].set(f"{st['el']:+.0f}°", t.main if up else t.dim,
                                    "IN VIEW" if up else "below horizon", led=t.main if up else None)
                self.tile["rng"].set(f"{st['range']:,.0f}", t.teal_edge, f"km · alt {st['alt']:,.0f} km")
                d145 = S.doppler_hz(145.8e6, st["rate"])
                self.tile["rr"].set(f"{st['rate']:+.2f}", t.purple, f"km/s · 2m {d145 / 1000:+.1f} kHz")
                self._draw_tx(st["rate"])
            p = self.sel_pass
            if p and hasattr(self, "_track"):
                self.sky.set(self._track, (st["az"], st["el"]) if st else None,
                             f"{p['name']}  ·  max {p['max_el']:.0f}°  ·  "
                             f"{time.strftime('%H:%M', time.localtime(p['aos']))}-"
                             f"{time.strftime('%H:%M', time.localtime(p['los']))} local")
        if int(now) % 30 == 0:
            self._fill_passes()
