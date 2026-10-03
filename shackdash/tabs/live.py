"""B · LIVE ACTIVITY: who's being heard where"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel

from .. import bandplan
from ..feeds import BANDS, HF_BANDS, band_of
from ..geo import bearing_distance, compass, grid_to_latlon
from ..instruments import HeatGrid, fill_table, make_table
from ..mapview import MapView
from ..theme import px
from ..widgets import DeckButton
from .base import Tab, ago, hline_search, key_row, note, panel, stretch

# NCDXF/IARU International Beacon Project: 18 beacons x 5 bands, 10 s each, 3-minute cycle
NCDXF = [("4U1UN", "United Nations NY", "FN30as"), ("VE8AT", "Eureka, Canada", "EQ79ax"),
         ("W6WX", "Mt Umunhum, CA", "CM97bd"), ("KH6RS", "Maui, Hawaii", "BL10ts"),
         ("ZL6B", "Masterton, NZ", "RE78tw"), ("VK6RBP", "Rolystone, WA", "OF87av"),
         ("JA2IGY", "Mt Asama, Japan", "PM84jk"), ("RR9O", "Novosibirsk", "NO14kx"),
         ("VR2B", "Hong Kong", "OL72bg"), ("4S7B", "Colombo, Sri Lanka", "MJ96wv"),
         ("ZS6DN", "Pretoria, S Africa", "KG44dc"), ("5Z4B", "Kikuyu, Kenya", "KI88hr"),
         ("4X6TU", "Tel Aviv, Israel", "KM72jb"), ("OH2B", "Lohja, Finland", "KP20dh"),
         ("CS3B", "Madeira", "IM12jt"), ("LU4AA", "Buenos Aires", "GF05tj"),
         ("OA4B", "Lima, Peru", "FH17mw"), ("YV5B", "Caracas", "FJ69cc")]
NCDXF_FREQS = [14100, 18110, 21150, 24930, 28200]

HEAT_BANDS = ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]


def ncdxf_now(ts: float):
    """[(band index, beacon index, seconds left in slot)] for the current 10 s slot."""
    slot = int(ts % 180 // 10)
    left = 10 - ts % 10
    return [(b, (slot - b) % 18, left) for b in range(5)]


class LiveTab(Tab):
    title = "B · LIVE"
    keys = ("psk_me", "psk_grid", "wspr", "land", "cty", "dxped")
    footer = ("DX cluster via telnet · Reverse Beacon Network · PSKReporter (N1DQ) · WSPR via wspr.live "
              "· NCDXF/IARU beacon schedule computed locally")

    def build(self):
        t = self.t
        self.band = "ALL"
        self.search = ""
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))

        self.cl_state = QLabel("")
        self.cl_state.setObjectName("note")
        keys = key_row(t, ["ALL"] + HF_BANDS + ["6m", "VHF+"], self._pick_band, height=30)
        top = QHBoxLayout()
        self.skim = DeckButton(t, "SKIMMERS", led=True)
        self.skim.setFixedSize(px(118), px(30))
        self.skim.setToolTip("Show CW/RTTY skimmer spots (spotters ending in -#). Off = human spots only.")
        self.skim.clicked.connect(self._toggle_skim)
        self.show_skim = False
        top.addWidget(self.skim)
        top.addWidget(self.cl_state, 1)
        top.addWidget(hline_search("filter call / country / comment", self._set_search), 1)
        self.cluster = make_table(["UTC", "kHz", "DX", "COUNTRY", "SPOTTER", "MODE", "COMMENT"],
                                  {0: 48, 1: 76, 2: 96, 3: 140, 4: 86, 5: 46}, stretch_col=6)
        g.addWidget(panel(t, "DX CLUSTER", [keys, top, self.cluster], dot=t.main), 0, 0, 2, 1)

        self.map = MapView(t, center_lon=self.ctx.qth[1])
        self.heard = make_table(["UTC", "SRC", "WHO", "BAND", "MODE", "SNR", "km", "WHERE"],
                                {0: 46, 1: 56, 2: 84, 3: 46, 4: 48, 5: 40, 6: 56}, stretch_col=7)
        self.heard_note = note("")
        g.addWidget(panel(t, f"WHERE {self.ctx.call or 'MY SIGNAL'} IS HEARD  ·  RBN · PSKReporter · WSPR",
                          self.map, dot=t.amber), 0, 1)
        g.addWidget(panel(t, "WHO HEARS ME  (and WSPR I hear)", [self.heard_note, self.heard], dot=t.amber), 1, 1)

        self.heat = HeatGrid(t)
        self.best = make_table(["BAND", "SPOTS", "BEST DX", "km"], {0: 50, 1: 50, 2: 150}, stretch_col=3)
        self.heat_note = note("")
        g.addWidget(panel(t, "BAND ACTIVITY  ·  MY GRID FIELD ↔ CONTINENTS (1 h)",
                          [stretch(self.heat, 3), self.heat_note, stretch(self.best, 2)], dot=t.sub), 0, 2)
        self.bcn = make_table(["MHz", "NOW", "LOCATION", "BEARING", "NEXT"], {0: 50, 1: 66, 3: 72, 4: 84},
                              stretch_col=2)
        g.addWidget(panel(t, "NCDXF / IARU BEACONS  ·  ON AIR NOW", [self.bcn, note(
            "Each beacon sends its call then four 1-second dashes at 100 W, 10 W, 1 W and 0.1 W. Hearing the "
            "weaker dashes means the path is wide open.")], dot=t.purple), 1, 2)
        g.setColumnStretch(0, 44)
        g.setColumnStretch(1, 33)
        g.setColumnStretch(2, 28)
        g.setRowStretch(0, 1)
        g.setRowStretch(1, 1)
        self.ctx.spotsChanged.connect(self._spots_dirty)
        self.ctx.heardChanged.connect(self._heard)
        self._dirty = True
        self._last_draw = 0.0
        self._active_dx: set[str] = set()
        self.tick()
        self._heard()

    # ---- cluster --------------------------------------------------------------------
    def _pick_band(self, b):
        self.band = b
        self._dirty = True
        self._draw_spots()

    def _toggle_skim(self):
        self.show_skim = not self.show_skim
        self.skim.set_state(active=self.show_skim)
        self._dirty = True
        self._draw_spots()

    def _set_search(self, s):
        self.search = s.strip().upper()
        self._dirty = True
        self._draw_spots()

    def _spots_dirty(self):
        self._dirty = True
        if time.time() - self._last_draw > 1.0:
            self._draw_spots()

    def _band_ok(self, sp) -> bool:
        if self.band == "ALL":
            return True
        if self.band == "VHF+":
            return sp["khz"] >= 60000
        return sp["band"] == self.band

    def _draw_spots(self):
        if not self._dirty or not self.isVisible() and self._last_draw:
            return
        self._dirty = False
        self._last_draw = time.time()
        cty = self.ctx.cty
        rows, colors, tips = [], [], []
        me = self.ctx.call
        level = self.ctx.cfg.get("licence", "Advanced")
        for sp in self.ctx.spots:
            if not self._band_ok(sp) or (not self.show_skim and sp["spotter"].endswith("-#")):
                continue
            ent = cty.lookup(sp["dx"]) if cty else None
            country = ent.name if ent else ""
            if self.search and self.search not in f"{sp['dx']} {country.upper()} {sp['comment'].upper()} {sp['spotter']}":
                continue
            rows.append((sp["time"], f"{sp['khz']:.1f}", sp["dx"], country, sp["spotter"], sp["mode"], sp["comment"]))
            base = sp["dx"].split("/")[0]
            ok, _why = bandplan.check(sp["khz"], level)
            colors.append(self.t.amber if base == me else self.t.purple if sp["dx"] in self._active_dx
                          else self.t.faint if not ok else self.t.main if time.time() - sp["t"] < 90 else None)
            tips.append("Active DXpedition (NG3K)" if sp["dx"] in self._active_dx else
                        "" if ok else f"Outside {level} privileges")
            if len(rows) >= 400:
                break
        fill_table(self.cluster, rows, colors, right={1}, tips=tips)

    # ---- who hears me -------------------------------------------------------------------
    def _heard(self):
        lat, lon = self.ctx.qth
        me = self.ctx.call
        cty = self.ctx.cty
        now = time.time()
        items = []                   # (ts, src, who, band, mode, snr, km, where, color, rlat, rlon)
        t = self.t

        def place(call, loc):
            ll = grid_to_latlon(loc) if loc else None
            ent = cty.lookup(call) if cty else None
            if not ll and ent:
                ll = (ent.lat, ent.lon)
            where = (ent.name if ent else "") + (f" {loc[:4]}" if loc else "")
            return ll, where
        for sp in self.ctx.rbn_me:
            ll, where = place(sp["spotter"], "")
            items.append((sp["t"], "RBN", sp["spotter"], sp["band"], sp.get("mode", ""), sp.get("snr", ""), ll, where,
                          t.main))
        for r in self.ctx.hub.data.get("psk_me", []) or []:
            ll, where = place(r["rx"], r["rx_loc"])
            items.append((r["t"], "PSK", r["rx"], band_of(r["f"] / 1000), r["mode"], r["snr"], ll, where, t.sub))
        for w in self.ctx.hub.data.get("wspr", []) or []:
            ts = _wspr_ts(w["time"])
            if w["tx_sign"].upper() == me:
                ll, where = place(w["rx_sign"], w["rx_loc"])
                items.append((ts, "WSPR", w["rx_sign"], band_of(w["frequency"] / 1000), "WSPR", w["snr"], ll, where,
                              t.purple))
            else:
                ll, where = place(w["tx_sign"], w["tx_loc"])
                items.append((ts, "WSPR-RX", w["tx_sign"], band_of(w["frequency"] / 1000), "WSPR", w["snr"], ll,
                              where, t.dim))
        items.sort(key=lambda i: -i[0])
        rows, colors, markers, paths = [], [], [], []
        for ts, src, who, band, mode, snr, ll, where, col in items[:400]:
            km = f"{bearing_distance(lat, lon, *ll)[1]:.0f}" if ll else ""
            rows.append((time.strftime("%H:%M", time.gmtime(ts)), src, who, band, mode, snr, km, where))
            colors.append(col)
        seen = set()
        from ..geo import gc_points
        for ts, src, who, band, mode, snr, ll, where, col in items:
            if not ll or who in seen or now - ts > 6 * 3600:
                continue
            seen.add(who)
            markers.append((ll[0], ll[1], col, "", 8))
            if len(paths) < 120:
                paths.append((gc_points(lat, lon, ll[0], ll[1], 40), col, 0.8, False))
        markers.append((lat, lon, t.amber, me or "QTH", 13))
        self.map.set_overlays(markers=markers, paths=paths,
                              caption="green RBN · blue PSKReporter · purple WSPR · grey WSPR I received (last 6 h)")
        fill_table(self.heard, rows, colors, right={5, 6})
        n_rbn = sum(1 for i in items if i[1] == "RBN")
        n_psk = sum(1 for i in items if i[1] == "PSK")
        n_w = sum(1 for i in items if i[1] == "WSPR")
        rbn = self.ctx.feed_state.get("RBN", ("", False))
        self.heard_note.setText(f"{n_rbn} RBN · {n_psk} PSKReporter (1 h) · {n_w} WSPR (24 h)   ·   RBN: {rbn[0]}"
                                if me else "Set your callsign in SETUP.")

    # ---- band activity ---------------------------------------------------------------------
    def _heatmap(self, reports):
        """Which band is open to which continent: reports with one end in my grid field."""
        field = self.ctx.cfg.get("grid", "QF")[:2].upper()
        cty = self.ctx.cty
        conts = ["EU", "NA", "SA", "AF", "AS", "OC"]
        vals = {b: [0] * len(conts) for b in HEAT_BANDS}
        best: dict[str, tuple[float, str, int]] = {}
        for r in reports:
            b = band_of(r["f"] / 1000)
            if b not in vals:
                continue
            mine_tx = r["tx_loc"][:2].upper() == field
            far_call, far_loc = (r["rx"], r["rx_loc"]) if mine_tx else (r["tx"], r["tx_loc"])
            ent = cty.lookup(far_call) if cty else None
            if ent and ent.cont in conts:
                vals[b][conts.index(ent.cont)] += 1
            a, z = grid_to_latlon(r["tx_loc"][:6]), grid_to_latlon(r["rx_loc"][:6])
            cnt = best.get(b, (0, "", 0))[2] + 1
            if a and z:
                km = bearing_distance(*a, *z)[1]
                if b not in best or km > best[b][0]:
                    best[b] = (km, far_call, cnt)
                    continue
            if b in best:
                best[b] = (best[b][0], best[b][1], cnt)
        self.heat.set_data(HEAT_BANDS, conts, [vals[b] for b in HEAT_BANDS],
                           "no PSKReporter reports yet" if cty else "waiting for the prefix database")
        rows = [(b, best[b][2], best[b][1], f"{best[b][0]:.0f}") for b in HEAT_BANDS if b in best]
        fill_table(self.best, rows, right={1, 3})
        self.heat_note.setText(f"{len(reports)} PSKReporter reports to/from grid field {field} in the last hour. "
                               "Cells count paths per band and continent (OC includes VK-VK).")

    def on_data(self, key, d):
        if key in ("psk_me", "wspr", "cty"):
            self._heard()
            if key == "cty":
                self._dirty = True
                self._draw_spots()
                if "psk_grid" in self.ctx.hub.data:
                    self._heatmap(self.ctx.hub.data["psk_grid"])
        elif key == "psk_grid":
            self._heatmap(d)
        elif key == "land":
            self.map.set_land(d)
        elif key == "dxped":
            now = time.time()
            self._active_dx = {x["call"].upper() for x in d if x["start"] and x["start"] <= now <= (x["end"] or 0)}

    def qth_changed(self):
        self.map.set_center(self.ctx.qth[1])
        self._heard()
        if "psk_grid" in self.ctx.hub.data:
            self._heatmap(self.ctx.hub.data["psk_grid"])

    def tick(self):
        now = time.time()
        lat, lon = self.ctx.qth
        rows, colors, tips = [], [], []
        for b, i, left in ncdxf_now(now):
            call, where, loc = NCDXF[i]
            nxt = NCDXF[(i + 1) % 18][0]
            ll = grid_to_latlon(loc)
            brg, km = bearing_distance(lat, lon, *ll)
            rows.append((f"{NCDXF_FREQS[b] / 1000:.3f}", call, where, f"{brg:.0f}° {compass(brg)}",
                         f"{nxt} {left:.0f}s"))
            colors.append(self.t.main)
            tips.append(f"{call} {where}: {km:,.0f} km, beam {brg:.0f}° (long path {(brg + 180) % 360:.0f}°)")
        fill_table(self.bcn, rows, colors, tips=tips)
        cs = self.ctx.feed_state.get("CLUSTER", ("not connected", False))
        self.cl_state.setText(f"{self.ctx.cfg.get('cluster')}  ·  {cs[0]}  ·  {len(self.ctx.spots)} spots")
        if self._dirty:
            self._draw_spots()


def _wspr_ts(s: str) -> float:
    import calendar
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0
