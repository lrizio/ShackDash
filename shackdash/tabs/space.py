"""A · SPACE WEATHER & HF PROPAGATION"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QTextBrowser, QWidget

from ..geo import bearing_distance
from ..instruments import BarPlot, StatTile, TrendPlot, fill_table, make_table
from ..mapview import MapView
from ..sources import xray_class
from ..theme import px
from ..widgets import font, paint_glow_dot, paint_recess, qc
from .base import Tab, ago, hhmm_utc, panel, stretch

COND_BANDS = ["80m-40m", "30m-20m", "17m-15m", "12m-10m"]


class CondGrid(QWidget):
    """N0NBH calculated band conditions: 4 band groups x day/night, LED pills."""

    def __init__(self, t):
        super().__init__()
        self.t = t
        self.bands: dict = {}
        self.vhf: list = []
        self.extra = ""
        self.setMinimumSize(px(220), px(150))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, bands, vhf, extra):
        self.bands, self.vhf, self.extra = bands, vhf, extra
        self.update()

    def color(self, s: str) -> str:
        t = self.t
        return {"Good": t.main, "Fair": t.amber, "Poor": t.red}.get(s, t.faint)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.t
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, t, px(10))
        vhf_rows = [v for v in self.vhf if v[2] and v[2] != "Band Closed"]
        n_rows = 1 + len(COND_BANDS)
        top = r.top() + px(8)
        h_tab = (r.height() - px(16)) * (0.72 if self.vhf else 1.0)
        rh = h_tab / n_rows
        c0 = r.left() + px(10)
        cw = (r.width() - px(20)) / 3
        p.setFont(font(min(px(12), rh * 0.5), bold=True))
        p.setPen(qc(t.dim))
        for j, name in enumerate(("BAND", "DAY", "NIGHT")):
            p.drawText(QRectF(c0 + j * cw, top, cw, rh), Qt.AlignmentFlag.AlignCenter if j else
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        for i, b in enumerate(COND_BANDS):
            y = top + (i + 1) * rh
            p.setFont(font(min(px(13), rh * 0.52), bold=True))
            p.setPen(qc(t.text))
            p.drawText(QRectF(c0, y, cw, rh), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, b)
            for j, when in enumerate(("day", "night")):
                s = self.bands.get(b, {}).get(when, "")
                col = self.color(s)
                cell = QRectF(c0 + (j + 1) * cw + px(6), y + rh * 0.14, cw - px(12), rh * 0.72)
                p.setPen(qc(col, 160))
                p.setBrush(qc(col, 38 if s else 0))
                p.drawRoundedRect(cell, cell.height() / 2, cell.height() / 2)
                paint_glow_dot(p, QPointF(cell.left() + cell.height() * 0.55, cell.center().y()), cell.height() * 0.6,
                               col, bool(s), t.led_off)
                p.setPen(qc(col if s else t.faint))
                p.drawText(cell.adjusted(cell.height() * 0.6, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, s or "--")
        y = top + h_tab + px(4)
        p.setFont(font(px(11.5)))
        p.setPen(qc(t.dim))
        lines = [self.extra] if self.extra else []
        lines += [f"{n.replace('vhf-aurora', 'VHF aurora').replace('E-Skip', 'Es')} {loc.replace('_', ' ')}: {s}"
                  for n, loc, s in (vhf_rows or self.vhf[:0])]
        if self.vhf and not vhf_rows:
            lines.append("VHF: aurora and sporadic-E all closed")
        p.drawText(QRectF(c0, y, r.width() - px(20), r.bottom() - y - px(4)),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, "\n".join(lines))


class SpaceTab(Tab):
    title = "A · SPACE WX"
    keys = ("hamqsl", "kp", "xray", "wind", "mag", "protons", "alerts", "scales", "ionosondes", "aurora", "land")
    footer = ("NOAA SWPC · solar-terrestrial data courtesy N0NBH (hamqsl.com) · ionosondes via prop.kc2g.com / GIRO "
              "· OVATION aurora model")

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        self.tile = {}
        for key, cap in (("sfi", "SOLAR FLUX"), ("ssn", "SUNSPOTS"), ("a", "A INDEX"), ("kp", "Kp NOW"),
                         ("xray", "X-RAY"), ("wind", "SOLAR WIND"), ("bz", "Bz (GSM)"), ("prot", "PROTONS ≥10MeV"),
                         ("scales", "NOAA R · S · G"), ("muf", "MUF NEAREST")):
            self.tile[key] = StatTile(t, cap)
            tiles.addWidget(self.tile[key])
        g.addWidget(panel(t, "NOW", tiles, dot=t.main, pad=8), 0, 0, 1, 3)

        self.cond = CondGrid(t)
        g.addWidget(panel(t, "HF BAND CONDITIONS (N0NBH)", self.cond, dot=t.main), 1, 0)
        self.kp = BarPlot(t, 9, {5: "G1", 6: "G2", 7: "G3", 8: "G4", 9: "G5"})
        g.addWidget(panel(t, "PLANETARY Kp  ·  OBSERVED + FORECAST", self.kp, dot=t.amber), 1, 1)
        self.xray = TrendPlot(t, log=True, ymin=1e-9, ymax=1e-3)
        self.xray.levels = [(1e-7, "B", t.dim), (1e-6, "C", t.amber), (1e-5, "M", t.red), (1e-4, "X", t.purple)]
        g.addWidget(panel(t, "GOES X-RAY FLUX  ·  24 h", self.xray, dot=t.red), 1, 2)

        self.speed = TrendPlot(t, "km/s")
        self.bz = TrendPlot(t, "nT")
        self.bz.shade_below_zero = t.red
        g.addWidget(panel(t, "SOLAR WIND  ·  SPEED + IMF", [self.speed, self.bz], dot=t.sub), 2, 0)
        self.prot = TrendPlot(t, "pfu", log=True, ymin=0.1, ymax=1e3)
        self.prot.levels = [(10, "S1", t.amber), (100, "S2", t.red)]
        g.addWidget(panel(t, "PROTON FLUX ≥10 MeV  ·  24 h", self.prot, dot=t.purple), 2, 1)
        self.iono = make_table(["IONOSONDE", "km", "MUFd", "foF2", "hmF2", "AGE"],
                               {0: 150, 1: 52, 2: 52, 3: 48, 4: 48, 5: 44})
        g.addWidget(panel(t, "NEAREST IONOSONDES  ·  MUF(3000) / foF2 MHz", self.iono, dot=t.teal_edge), 2, 2)

        self.alerts = make_table(["UTC", "CODE", "MESSAGE"], {0: 92, 1: 56}, stretch_col=2)
        self.alert_text = QTextBrowser()
        self.alert_text.setMaximumHeight(px(90))
        self.alerts.itemSelectionChanged.connect(self._alert_sel)
        g.addWidget(panel(t, "SWPC ALERTS · WATCHES · WARNINGS", [stretch(self.alerts, 3), stretch(self.alert_text, 1)],
                          dot=t.amber), 3, 0)
        self.aur = MapView(t, center_lon=self.ctx.qth[1], lat_range=(-90, -18), lon_span=190)
        self.aur.night = True
        g.addWidget(panel(t, "AURORA AUSTRALIS  ·  OVATION MODEL", self.aur, dot=t.main), 3, 1, 1, 2)
        for r, s in ((0, 12), (1, 30), (2, 30), (3, 26)):
            g.setRowStretch(r, s)
        for c in range(3):
            g.setColumnStretch(c, 1)
        self._alerts = []

    # ---- data ---------------------------------------------------------------------
    def on_data(self, key, d):
        t = self.t
        if key == "hamqsl":
            num = lambda s: float(s) if s.replace(".", "", 1).isdigit() else None
            sfi, ssn, a = num(d["solarflux"]), num(d["sunspots"]), num(d["aindex"])
            self.tile["sfi"].set(d["solarflux"] or "--", t.red if sfi and sfi < 70 else t.amber if sfi and sfi < 90
                                 else t.main, "sfu · " + d["updated"][-9:].strip(), led=t.main)
            self.tile["ssn"].set(d["sunspots"] or "--", t.teal_edge, "", led=t.main)
            self.tile["a"].set(d["aindex"] or "--", t.main if a is not None and a < 15 else t.amber if a is not None
                               and a < 30 else t.red, d["geomagfield"].title(), led=t.main)
            extra = f"Geomag: {d['geomagfield'].title()}   ·   Noise: {d['signalnoise']}"
            self.cond.set_data(d["bands"], d["vhf"], extra)
        elif key == "kp":
            now = time.time()
            bars = []
            for ts, kp, obs in d:
                if now - 3 * 86400 <= ts <= now + 3 * 86400:
                    col = t.main if kp < 4 else t.amber if kp < 5 else t.red
                    bars.append((ts, kp, col, obs == "predicted"))
            self.kp.set_bars(bars)
            last = [b for b in d if b[2] != "predicted" and b[0] <= now]
            if last:
                ts, kp, obs = last[-1]
                col = t.main if kp < 4 else t.amber if kp < 5 else t.red
                g = "" if kp < 5 else f" · G{min(5, int(kp) - 4)}"
                self.tile["kp"].set(f"{kp:.1f}", col, f"{obs} {hhmm_utc(ts)}z{g}", led=col)
        elif key == "xray":
            lt, lv = d["long"]
            st, sv = d["short"]
            self.xray.set_series([(st, sv, t.sub, "0.05-0.4nm"), (lt, lv, t.amber, "0.1-0.8nm")])
            if lv:
                cls = xray_class(lv[-1])
                peak6 = max((v for ts, v in zip(lt, lv) if ts > time.time() - 6 * 3600), default=None)
                col = t.red if cls[0] in "MX" else t.amber if cls[0] == "C" else t.main
                self.tile["xray"].set(cls, col, f"6 h peak {xray_class(peak6)}", led=col,
                                      tip="M-class and above cause HF radio blackouts (R1+) on the sunlit side")
        elif key == "wind":
            self.speed.set_series([(d["t"], d["proton_speed"], t.sub, "speed")])
            v = next((x for x in reversed(d["proton_speed"]) if x is not None), None)
            n = next((x for x in reversed(d["proton_density"]) if x is not None), None)
            if v:
                col = t.main if v < 500 else t.amber if v < 700 else t.red
                self.tile["wind"].set(f"{v:.0f}", col, f"km/s · {n:.1f} p/cc" if n else "km/s", led=col)
        elif key == "mag":
            self.bz.set_series([(d["t"], d["bt"], t.dim, "Bt"), (d["t"], d["bz_gsm"], t.red, "Bz")])
            bz = next((x for x in reversed(d["bz_gsm"]) if x is not None), None)
            if bz is not None:
                col = t.main if bz > -5 else t.amber if bz > -10 else t.red
                self.tile["bz"].set(f"{bz:+.1f}", col, "nT · south = storm fuel" if bz < 0 else "nT · northward", led=col)
        elif key == "protons":
            ts, vs = d
            self.prot.set_series([(ts, vs, t.purple, "≥10MeV")])
            if vs:
                v = vs[-1]
                col = t.main if v < 10 else t.amber if v < 100 else t.red
                self.tile["prot"].set(f"{v:.2g}", col, "pfu · S1 at 10 · polar HF", led=col)
        elif key == "scales":
            cur = d.get("0", {})
            vals = [(k, cur.get(k, {}).get("Scale")) for k in ("R", "S", "G")]
            txt = "  ".join(f"{k}{v or 0}" for k, v in vals)
            worst = max(int(v or 0) for _, v in vals)
            col = t.main if worst == 0 else t.amber if worst < 3 else t.red
            d1 = d.get("1", {})
            prob = (f"R {d1.get('R', {}).get('MinorProb') or '-'}% · S {d1.get('S', {}).get('Prob') or '-'}% · "
                    f"G{d1.get('G', {}).get('Scale') or '0'}")
            self.tile["scales"].set(txt, col, f"24h {prob}", led=col)
        elif key == "ionosondes":
            lat, lon = self.ctx.qth
            now = time.time()
            rows = []
            for s in d:
                brg, dist = bearing_distance(lat, lon, s["lat"], s["lon"])
                rows.append((dist, s))
            rows.sort(key=lambda r: r[0])
            fresh = [(dist, s) for dist, s in rows if now - s["t"] < 3 * 3600]
            show = (fresh[:8] if fresh else rows[:8])
            fmt = lambda v, n=1: "" if v is None else f"{v:.{n}f}"
            fill_table(self.iono, [(s["name"].replace(", Australia", ""), f"{dist:.0f}", fmt(s["mufd"]),
                                    fmt(s["fof2"], 2), fmt(s["hmf2"], 0), ago(s["t"])) for dist, s in show],
                       colors=[None if now - s["t"] < 3600 else self.t.dim for _, s in show], right={1, 2, 3, 4, 5})
            if fresh:
                dist, s = fresh[0]
                self.tile["muf"].set(f"{s['mufd']:.1f}" if s["mufd"] else "--", t.teal_edge,
                                     f"MHz · {s['name'].split(',')[0]} · {ago(s['t'])}", led=t.main,
                                     tip="MUF(3000) from the nearest ionosonde reporting in the last 3 h")
        elif key == "alerts":
            self._alerts = d
            fill_table(self.alerts, [(time.strftime("%d %H:%Mz", time.gmtime(a["t"])), a["id"], a["head"])
                                     for a in d],
                       colors=[self.t.red if a["head"].startswith(("ALERT", "WARNING")) and time.time() - a["t"] < 86400
                               else None for a in d])
            if d and not self.alert_text.toPlainText():
                self.alerts.selectRow(0)
        elif key in ("aurora", "land"):
            if key == "land":
                self.aur.set_land(d)
            else:
                lat, lon = self.ctx.qth
                self.aur.set_overlays(heat=(d["grid"], t.main),
                                      markers=[(lat, lon, t.amber, self.ctx.call or "QTH", 11)],
                                      caption=f"forecast for {d['fc'][11:16]} UTC  ·  green = probability of visible aurora")

    def _alert_sel(self):
        rows = self.alerts.selectionModel().selectedRows()
        if rows and rows[0].row() < len(self._alerts):
            self.alert_text.setPlainText(self._alerts[rows[0].row()]["text"])

    def qth_changed(self):
        self.aur.set_center(self.ctx.qth[1])
        for k in ("ionosondes", "aurora"):
            if k in self.ctx.hub.data:
                self.on_data(k, self.ctx.hub.data[k])

    def tick(self):
        self.kp.update()
