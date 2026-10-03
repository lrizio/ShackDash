"""C · LOCAL: clocks, sun, moon/EME, grey line and beam headings (all computed here)"""
from __future__ import annotations

import re
import time

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from .. import astro
from ..geo import bearing_distance, compass, gc_points, grid_to_latlon, latlon_to_grid
from ..instruments import StatTile, fill_table, make_table
from ..mapview import MapView
from ..theme import px
from .base import Tab, note, panel

DX_AREAS = [("Europe (Brussels)", 50.85, 4.35), ("UK (London)", 51.5, -0.12), ("USA East (New York)", 40.7, -74.0),
            ("USA Central (Chicago)", 41.9, -87.6), ("USA West (Los Angeles)", 34.05, -118.25),
            ("Caribbean (Puerto Rico)", 18.2, -66.5), ("South America (Buenos Aires)", -34.6, -58.4),
            ("Southern Africa (Johannesburg)", -26.2, 28.0), ("Middle East (Dubai)", 25.2, 55.3),
            ("India (Delhi)", 28.6, 77.2), ("Japan (Tokyo)", 35.7, 139.7), ("Hawaii", 21.3, -157.8),
            ("New Zealand (Wellington)", -41.3, 174.8), ("Antarctica (Casey)", -66.3, 110.5)]


def fmt_local(ts):
    return time.strftime("%H:%M", time.localtime(ts)) if ts else "--"


class LocalTab(Tab):
    title = "C · LOCAL"
    keys = ("land", "cty")
    footer = "Sun, moon, grey line, beam headings and EME figures are calculated on this PC (no internet needed)"

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        clock = QHBoxLayout()
        clock.setSpacing(px(8))
        self.utc = StatTile(t, "UTC", max_px=64)
        self.loc = StatTile(t, "LOCAL", max_px=64)
        clock.addWidget(self.utc, 3)
        clock.addWidget(self.loc, 3)
        self.tile = {}
        for k, cap in (("rise", "SUNRISE"), ("set", "SUNSET"), ("len", "DAYLIGHT"), ("sun", "SUN AZ / EL")):
            self.tile[k] = StatTile(t, cap)
            clock.addWidget(self.tile[k], 2)
        g.addWidget(panel(t, "TIME & SUN", clock, dot=t.amber, pad=8), 0, 0, 1, 2)
        moon = QHBoxLayout()
        moon.setSpacing(px(8))
        for k, cap in (("phase", "MOON"), ("mpos", "MOON AZ / EL"), ("mrise", "RISE / SET"), ("eme", "EME LOSS")):
            self.tile[k] = StatTile(t, cap)
            moon.addWidget(self.tile[k])
        g.addWidget(panel(t, "MOON & EME", moon, dot=t.purple, pad=8), 0, 2)

        self.map = MapView(t, center_lon=self.ctx.qth[1])
        self.map.clicked.connect(self._map_click)
        g.addWidget(panel(t, "GREY LINE  ·  click the map to aim", self.map, dot=t.amber), 1, 0, 2, 2)

        self.target = QLineEdit()
        self.target.setPlaceholderText("callsign, prefix, grid (QF22) or lat, lon")
        self.target.textChanged.connect(self._aim)
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        for k, cap in (("sp", "SHORT PATH"), ("lp", "LONG PATH")):
            self.tile[k] = StatTile(t, cap)
            tiles.addWidget(self.tile[k])
        self.aim_note = note("")
        box = QVBoxLayout()
        box.addWidget(self.target)
        box.addLayout(tiles, 1)
        box.addWidget(self.aim_note)
        g.addWidget(panel(t, "BEAM HEADING", box, dot=t.main), 1, 2)
        self.areas = make_table(["DX AREA", "SP", "LP", "km", "THERE"], {0: 190, 1: 70, 2: 56, 3: 60}, stretch_col=4)
        g.addWidget(panel(t, "BEARINGS FROM MY QTH", self.areas, dot=t.sub), 2, 2)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        g.setRowStretch(0, 11)
        g.setRowStretch(1, 16)
        g.setRowStretch(2, 32)
        self._aim_pt = None
        self._slow = 0
        self.tick()

    def on_data(self, key, d):
        if key == "land":
            self.map.set_land(d)
        elif key == "cty":
            self._aim(self.target.text())

    def qth_changed(self):
        self.map.set_center(self.ctx.qth[1])
        self._slow = 0
        self._aim(self.target.text())
        self.tick()

    def _map_click(self, lat, lon):
        self.target.setText(f"{lat:.2f}, {lon:.2f}")

    def _aim(self, text):
        text = text.strip()
        pt, label = None, ""
        m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)", text)
        if m:
            pt = (float(m[1]), float(m[2]))
            label = latlon_to_grid(*pt)
        elif grid_to_latlon(text) and len(text) in (4, 6, 8) and text[2:4].isdigit():
            pt = grid_to_latlon(text)
            label = text.upper()
        elif text and self.ctx.cty:
            ent = self.ctx.cty.lookup(text)
            if ent:
                pt = (ent.lat, ent.lon)
                label = f"{ent.name} ({ent.cont}, CQ {ent[3]})"
        self._aim_pt = (pt, label) if pt else None
        lat, lon = self.ctx.qth
        t = self.t
        if pt:
            brg, km = bearing_distance(lat, lon, *pt)
            lp = (brg + 180) % 360
            self.tile["sp"].set(f"{brg:.0f}°", t.main, f"{compass(brg)} · {km:,.0f} km", led=t.main)
            self.tile["lp"].set(f"{lp:.0f}°", t.sub, f"{compass(lp)} · {40030 - km:,.0f} km", led=t.sub)
            s = astro.sun(time.time())
            alt = astro.alt_az(s, *pt)[0]
            there = "daylight" if alt > 0 else "grey line" if alt > -6 else "dark"
            self.aim_note.setText(f"{label}  ·  sun at the far end: {alt:+.0f}° ({there})")
        else:
            self.tile["sp"].set("--", t.dim, "")
            self.tile["lp"].set("--", t.dim, "")
            self.aim_note.setText("Type a callsign/prefix (uses the country centre), a grid square, or lat, lon."
                                  if text else "Type a target, or click the map.")
        self._draw_map()

    def _draw_map(self):
        now = time.time()
        t = self.t
        lat, lon = self.ctx.qth
        s, m = astro.sun(now), astro.moon(now)
        markers = [(*astro.subpoint(s), t.amber, "SUN", 16), (*astro.subpoint(m), "#dfe6ee", "MOON", 12),
                   (lat, lon, t.main, self.ctx.call or "QTH", 13)]
        paths = []
        if self._aim_pt:
            pt, label = self._aim_pt
            paths.append((gc_points(lat, lon, *pt, 120), t.main, 1.6, False))
            paths.append((gc_points(lat, lon, *pt, 200, long_path=True), t.sub, 1.0, True))
            markers.append((pt[0], pt[1], t.red, "", 11))
        self.map.set_overlays(markers=markers, paths=paths,
                              caption="amber band = grey line (sun 0 to -6°) · solid = short path · dashed = long path")

    def tick(self):
        now = time.time()
        t = self.t
        self.utc.set(time.strftime("%H:%M:%S", time.gmtime(now)), t.main,
                     time.strftime("%a %d %b %Y", time.gmtime(now)) + "  ·  UTC", led=t.main)
        tzname = time.strftime("%Z", time.localtime(now))
        tzabbr = "".join(w[0] for w in tzname.split()) if " " in tzname else tzname
        self.loc.set(time.strftime("%H:%M:%S", time.localtime(now)), t.sub,
                     time.strftime("%a %d %b %Y", time.localtime(now)) + f"  ·  {tzabbr}", led=t.sub)
        self._slow -= 1
        if self._slow > 0:
            return
        self._slow = 20                                   # the rest only needs refreshing every 20 s
        lat, lon = self.ctx.qth
        day0 = astro.local_midnight(now)
        ev = astro.sun_events(lat, lon, day0)
        up, down = ev.get("rise_set_up"), ev.get("rise_set_down")
        self.tile["rise"].set(fmt_local(up), t.amber, f"civil dawn {fmt_local(ev.get('civil_up'))}",
                              led=t.amber if up and now < up else None)
        self.tile["set"].set(fmt_local(down), t.amber, f"civil dusk {fmt_local(ev.get('civil_down'))}",
                             led=t.amber if down and now < down else None)
        if up and down:
            dl = (down - up) / 3600
            self.tile["len"].set(f"{int(dl)}h {int(dl % 1 * 60):02d}m", t.teal_edge,
                                 f"{time.strftime('%H%M', time.gmtime(up))}-"
                                 f"{time.strftime('%H%M', time.gmtime(down))} UTC", led=t.main)
        s = astro.sun(now)
        alt, az = astro.alt_az(s, lat, lon)
        self.tile["sun"].set(f"{az:.0f}° / {alt:+.0f}°", t.amber if alt > 0 else t.dim,
                             "above horizon" if alt > 0 else "grey line" if alt > -6 else "below horizon",
                             led=t.amber if alt > 0 else None)
        ph = astro.moon_phase(now)
        m = astro.moon(now)
        malt, maz = astro.alt_az(m, lat, lon)
        self.tile["phase"].set(f"{ph['illum'] * 100:.0f}%", "#dfe6ee", ph["name"],
                               led="#dfe6ee")
        self.tile["mpos"].set(f"{maz:.0f}° / {malt:+.0f}°", t.main if malt > 0 else t.dim,
                              "up now" if malt > 0 else "below horizon",
                              led=t.main if malt > 0 else None)
        evs = astro.moon_events(lat, lon, now - 3600, 30)
        nxt_rise = next((ts for ts, r in evs if r and ts > now), None)
        nxt_set = next((ts for ts, r in evs if not r and ts > now), None)
        self.tile["mrise"].set(f"{fmt_local(nxt_rise)} / {fmt_local(nxt_set)}", t.teal_edge, "moon, local",
                               led=None)
        deg = astro.eme_degradation_db(m["dist_km"])
        self.tile["eme"].set(f"{deg:.1f} dB", t.main if deg < 1 else t.amber if deg < 1.6 else t.red,
                             f"{m['dist_km'] / 1000:.0f}k km", led=t.main if malt > 0 else None,
                             tip="Extra path loss compared with the moon at perigee (distance term only; "
                                 "sky temperature not included). Range is about 0 to 2.3 dB.")
        rows, colors = [], []
        for name, alat, alon in DX_AREAS:
            brg, km = bearing_distance(lat, lon, alat, alon)
            salt = astro.alt_az(s, alat, alon)[0]
            there = "daylight" if salt > 0 else "grey line" if salt > -6 else "dark"
            rows.append((name, f"{brg:.0f}° {compass(brg)}", f"{(brg + 180) % 360:.0f}°", f"{km:,.0f}",
                         there))
            colors.append(t.amber if there == "grey line" else None)
        fill_table(self.areas, rows, colors, right={3})
        self._draw_map()
