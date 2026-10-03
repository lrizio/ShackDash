"""L · APRS: stations, objects and weather heard on APRS-IS around the QTH
(receive only: a read-only login, nothing is ever transmitted)."""
from __future__ import annotations

import math
import time

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel

from ..aprs import DIGI_SYMS
from ..geo import EARTH_KM, bearing_distance, compass
from ..instruments import fill_table, make_table
from ..mapview import MapView
from ..theme import px
from .base import Tab, ago, hline_search, key_row, note, panel, stretch

FILTERS = ["ALL", "MOBILE", "FIXED", "WX", "DIGI / IGATE", "OBJECTS"]
MOBILE = {">", "k", "u", "v", "j", "R", "<", "b", "[", "O", "^", "'", "s", "Y", "a", "f", "p", "=", "U", "X"}


def destination(lat, lon, brg, km):
    d, b = km / EARTH_KM, math.radians(brg)
    la, lo = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


class AprsTab(Tab):
    title = "L · APRS"
    keys = ("land50",)
    footer = ("APRS-IS (aprs2.net tier-2 servers), receive-only login with a range filter around the QTH. Nothing is "
              "transmitted. Stations older than 6 hours are dropped.")

    def build(self):
        t = self.t
        self.filter, self.search = "ALL", ""
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.map = MapView(t)
        self.map.night = False
        self.state = QLabel("")
        self.state.setObjectName("note")
        g.addWidget(panel(t, "APRS AROUND MY QTH", [self.state, stretch(self.map, 1)], dot=t.main), 0, 0, 2, 1)
        top = QHBoxLayout()
        top.addLayout(key_row(t, FILTERS, self._pick, height=30), 3)
        top.addWidget(hline_search("filter call / comment", self._set_search), 1)
        self.table = make_table(["CALL", "WHAT", "km", "BRG", "HEARD", "PKTS", "km/h", "COMMENT"],
                                {0: 100, 1: 110, 2: 50, 3: 50, 4: 50, 5: 44, 6: 50}, stretch_col=7)
        self.table.itemSelectionChanged.connect(self._selected)
        self.sel = note("Select a station to see its track and details. Moving stations leave a trail.")
        g.addWidget(panel(t, "STATIONS · OBJECTS · WEATHER", [top, stretch(self.table, 1), self.sel], dot=t.amber),
                    0, 1)
        self.log = make_table(["UTC", "FROM", "TYPE", "PACKET"], {0: 60, 1: 100, 2: 70}, stretch_col=3)
        self.show_msgs = False
        g.addWidget(panel(t, "PACKETS AS THEY ARRIVE", [key_row(t, ["ALL PACKETS", "MESSAGES + BULLETINS"],
                                                                 self._pick_log, height=28), self.log], dot=t.sub),
                    1, 1)
        g.setColumnStretch(0, 52)
        g.setColumnStretch(1, 48)
        g.setRowStretch(0, 60)
        g.setRowStretch(1, 40)
        self._dirty = True
        self._last = 0.0
        self._selname = None
        self.ctx.aprsChanged.connect(self._mark)
        self._frame_map()

    def _frame_map(self):
        lat, lon = self.ctx.qth
        km = float(self.ctx.cfg.get("aprs_km", 150))
        dlat = km / 111.0 * 1.15
        self.map.lat_lo, self.map.lat_hi = lat - dlat, lat + dlat
        self.map.span = 2 * dlat / max(0.2, math.cos(math.radians(lat)))
        self.map.center_lon = lon
        self.map._land_path = None
        self.map._bg = None
        self.map.update()

    def on_data(self, key, d):
        if key == "land50":
            self.map.set_land(d)

    def _mark(self):
        self._dirty = True

    def _pick(self, f):
        self.filter = f
        self._dirty = True
        self._draw()

    def _pick_log(self, which):
        self.show_msgs = which.startswith("MESSAGES")
        self._dirty = True
        self._draw()

    def _set_search(self, s):
        self.search = s.strip().upper()
        self._dirty = True
        self._draw()

    def _cat(self, st) -> str:
        sym = st.get("sym", "")
        if st["kind"] == "object":
            return "OBJECTS"
        if st["kind"] == "weather" or sym == "_":
            return "WX"
        if sym in DIGI_SYMS:
            return "DIGI / IGATE"
        if sym in MOBILE or (st.get("speed_kt") or 0) > 3:
            return "MOBILE"
        return "FIXED"

    def _visible(self):
        lat, lon = self.ctx.qth
        out = []
        for st in self.ctx.aprs.values():
            if self.filter != "ALL" and self._cat(st) != self.filter:
                continue
            if self.search and self.search not in f"{st['name']} {st.get('comment', '')} {st.get('what', '')}".upper():
                continue
            if "lat" in st:
                st["brg"], st["km"] = bearing_distance(lat, lon, st["lat"], st["lon"])
            out.append(st)
        out.sort(key=lambda s: s["t"], reverse=True)
        return out

    def _draw(self):
        if not self._dirty:
            return
        self._dirty = False
        self._last = time.time()
        t = self.t
        vis = self._visible()
        self._vis = vis
        rows, colors = [], []
        catcol = {"MOBILE": t.amber, "WX": t.sub, "DIGI / IGATE": t.purple, "OBJECTS": t.teal_edge, "FIXED": t.main}
        for st in vis[:500]:
            spd = st.get("speed_kt")
            rows.append((st["name"], st.get("what", st["kind"]), f"{st['km']:.0f}" if "km" in st and "lat" in st else "",
                         f"{st['brg']:.0f}" if "brg" in st and "lat" in st else "", ago(st["t"]), st["n"],
                         f"{spd * 1.852:.0f}" if spd else "", self._detail(st)))
            colors.append(catcol.get(self._cat(st)) if time.time() - st["t"] < 600 else None)
        fill_table(self.table, rows, colors, right={2, 3, 5, 6})
        # map
        lat, lon = self.ctx.qth
        markers, paths = [], []
        km = float(self.ctx.cfg.get("aprs_km", 150))
        for ring in (km / 3, 2 * km / 3, km):
            pts = [destination(lat, lon, b, ring) for b in range(0, 361, 6)]
            paths.append((pts, t.faint, 0.8, True))
        near = sorted((s for s in vis if "lat" in s), key=lambda s: s.get("km", 1e9))
        for i, st in enumerate(near):
            col = catcol.get(self._cat(st), t.main)
            fresh = time.time() - st["t"] < 1800
            if len(st["track"]) > 1:
                paths.append(([(la, lo) for _t, la, lo in st["track"]], col, 1.2 if st["name"] != self._selname else 2.4,
                              False))
            label = st["name"] if (i < 30 or st["name"] == self._selname) else ""
            markers.append((st["lat"], st["lon"], col if fresh else t.dim, label, 9 if st["name"] == self._selname else 6))
        markers.append((lat, lon, t.red, self.ctx.call or "QTH", 11))
        self.map.set_overlays(markers=markers, paths=paths,
                              caption=f"rings {km / 3:.0f} / {2 * km / 3:.0f} / {km:.0f} km · amber mobile · green fixed "
                                      "· blue WX · purple digi/igate · grey = quiet 30 min+")
        # packet log
        log, lcol = [], []
        for p in self.ctx.aprs_log:
            if self.show_msgs and p["kind"] != "message":
                continue
            txt = (f"→ {p['to']}: {p['text']}" if p["kind"] == "message" else p["raw"].split(":", 1)[-1])
            log.append((time.strftime("%H:%M:%S", time.gmtime(p["t"])), p.get("obj") or p["src"], p["kind"], txt))
            me = self.ctx.call
            lcol.append(t.red if p["kind"] == "message" and me and p.get("to", "").split("-")[0] == me else
                        t.amber if p["kind"] == "message" else None)
            if len(log) >= 250:
                break
        fill_table(self.log, log, lcol)
        feed = self.ctx.feed_state.get("APRS")
        n_pos = sum(1 for s in self.ctx.aprs.values() if "lat" in s)
        self.state.setText((feed[0] if feed else "APRS feed off (turn it on in SETUP)") +
                           f"   ·   {len(self.ctx.aprs)} stations/objects, {n_pos} with positions, "
                           f"{len(self.ctx.aprs_log)} packets")

    @staticmethod
    def _detail(st) -> str:
        bits = []
        if st.get("temp_c") is not None:
            bits.append(f"{st['temp_c']:.1f}°C")
        if st.get("wind_kmh") is not None:
            bits.append(f"wind {st['wind_kmh']:.0f} km/h")
        if st.get("alt_ft"):
            bits.append(f"{st['alt_ft'] * 0.3048:.0f} m")
        if st.get("comment"):
            bits.append(st["comment"])
        return " · ".join(bits)

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(getattr(self, "_vis", [])):
            return
        st = self._vis[rows[0].row()]
        self._selname = st["name"]
        bits = [st["name"], st.get("what", "")]
        if "lat" in st:
            bits.append(f"{st['lat']:.4f}, {st['lon']:.4f}")
            bits.append(f"{st['km']:.1f} km at {st['brg']:.0f}° {compass(st['brg'])}")
        if st.get("course") is not None and st.get("speed_kt"):
            bits.append(f"heading {st['course']}° at {st['speed_kt'] * 1.852:.0f} km/h")
        bits.append(f"first heard {ago(st['first'])} ago, {st['n']} packets")
        if st["via"] != st["name"]:
            bits.append(f"object from {st['via']}")
        self.sel.setText(" · ".join(b for b in bits if b))
        self._dirty = True
        self._draw()

    def qth_changed(self):
        self._frame_map()
        self._dirty = True

    def tick(self):
        if time.time() - self._last > 2:
            self._dirty = True if int(time.time()) % 15 == 0 else self._dirty
            self._draw()
