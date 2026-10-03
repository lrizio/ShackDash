"""J · SUN: NOAA 27-day outlook, solar cycle progress, D-RAP HF absorption and
live solar imagery (SDO, SOHO LASCO)."""
from __future__ import annotations

import time

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from ..instruments import BarPlot, DatePlot, StatTile
from ..theme import px
from .base import Tab, key_row, note, panel, stretch
from .vhf import ImageScreen

SDO = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_{}.jpg"
IMAGES = [  # key, url, what it shows
    ("AIA 193", SDO.format("0193"), "SDO AIA 193 Å: corona; dark patches are coronal holes (fast wind, Kp up ~3 days later)"),
    ("AIA 171", SDO.format("0171"), "SDO AIA 171 Å: quiet corona and coronal loops over active regions"),
    ("AIA 304", SDO.format("0304"), "SDO AIA 304 Å: chromosphere, filaments and prominences"),
    ("AIA 131", SDO.format("0131"), "SDO AIA 131 Å: flaring regions (the hottest plasma)"),
    ("SUNSPOTS", SDO.format("HMIIC"), "SDO HMI continuum: the visible disk and its sunspots"),
    ("MAGNETO", SDO.format("HMIB"), "SDO HMI magnetogram: magnetic polarity (complex regions flare)"),
    ("LASCO C2", "https://soho.nascom.nasa.gov/data/realtime/c2/512/latest.jpg",
     "SOHO LASCO C2 coronagraph: CMEs leaving the sun (a halo = Earth-directed)"),
    ("LASCO C3", "https://soho.nascom.nasa.gov/data/realtime/c3/512/latest.jpg",
     "SOHO LASCO C3 wide coronagraph: CMEs out to 30 solar radii"),
]


class SunTab(Tab):
    title = "J · SUN"
    keys = ("outlook27", "cycle_obs", "cycle_pred", "drap")
    footer = ("NOAA SWPC 27-day outlook, solar cycle and D-RAP (public domain) · SDO images courtesy NASA/SDO and the "
              "AIA and HMI science teams · SOHO LASCO (ESA & NASA)")

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        self.tile = {}
        for k, cap in (("kp7", "MAX Kp · NEXT 7 DAYS"), ("flux7", "FLUX · NEXT 7 DAYS"), ("quiet", "QUIET DAYS AHEAD"),
                       ("storm", "NEXT STORM DAY"), ("ssn", "SMOOTHED SSN"), ("pred", "PREDICTED SSN NOW")):
            self.tile[k] = StatTile(t, cap)
            tiles.addWidget(self.tile[k])
        g.addWidget(panel(t, "PLANNING AHEAD", tiles, dot=t.main, pad=8), 0, 0, 1, 2)

        self.flux = DatePlot(t, "sfu")
        self.kp = BarPlot(t, 9, {5: "G1", 6: "G2", 7: "G3"})
        self.kp.label_every = 4
        self.issued = note("")
        g.addWidget(panel(t, "NOAA 27-DAY OUTLOOK  ·  10.7 cm FLUX, A INDEX AND LARGEST Kp",
                          [stretch(self.flux, 5), stretch(self.kp, 4), self.issued], dot=t.amber), 1, 0)
        self.cycle = DatePlot(t, ymin=0)
        self.cycle_note = note("")
        g.addWidget(panel(t, "SOLAR CYCLE  ·  SUNSPOT NUMBER, OBSERVED AND PREDICTED",
                          [self.cycle, self.cycle_note], dot=t.teal_edge), 2, 0)

        self.drap = ImageScreen(t)
        self.drap.msg = "loading D-RAP…"
        g.addWidget(panel(t, "D-RAP  ·  HF ABSORPTION NOW (flares and polar cap events)",
                          [self.drap, note("Colours show the highest frequency (MHz) losing 1 dB to D-layer "
                                           "absorption. Blank map = no fade. A flare fades the sunlit side; "
                                           "a proton event blacks out the poles.")], dot=t.red), 1, 1)
        self.img = ImageScreen(t)
        self.img.msg = "loading image…"
        self.img_note = note("")
        self.img_cache: dict[str, tuple[float, QImage]] = {}
        self.cur_img = IMAGES[0][0]
        g.addWidget(panel(t, "THE SUN NOW", [key_row(t, [k for k, _u, _d in IMAGES], self._pick, height=28),
                                            stretch(self.img, 1), self.img_note], dot=t.amber), 2, 1)
        g.setRowStretch(0, 12)
        g.setRowStretch(1, 44)
        g.setRowStretch(2, 44)
        g.setColumnStretch(0, 50)
        g.setColumnStretch(1, 50)
        self._pick(self.cur_img)

    # ---- data -------------------------------------------------------------------------
    def on_data(self, key, d):
        t = self.t
        if key == "outlook27":
            rows = d["rows"]
            now = time.time()
            self.flux.set_data([([r[0] for r in rows], [r[1] for r in rows], t.amber, "10.7 cm flux (sfu)", False),
                                ([r[0] for r in rows], [r[2] for r in rows], t.sub, "planetary A index", True)],
                               x_range=(rows[0][0], rows[-1][0]) if rows else None)
            self.kp.set_bars([(r[0], r[3], t.main if r[3] < 4 else t.amber if r[3] < 5 else t.red, True)
                              for r in rows])
            ahead = [r for r in rows if r[0] >= now - 86400]
            week = ahead[:7]
            if week:
                kpm = max(r[3] for r in week)
                col = t.main if kpm < 4 else t.amber if kpm < 5 else t.red
                self.tile["kp7"].set(str(kpm), col, "G" + str(kpm - 4) + " storm expected" if kpm >= 5 else
                                     "unsettled" if kpm == 4 else "quiet", led=col)
                fl = [r[1] for r in week]
                self.tile["flux7"].set(f"{min(fl)}–{max(fl)}", t.amber, "sfu (higher = better HF)", led=t.main)
            quiet = sum(1 for r in ahead if r[3] <= 2)
            self.tile["quiet"].set(f"{quiet}/{len(ahead)}", t.main, "days with Kp ≤ 2 (low noise, best DX)",
                                   led=t.main)
            storm = next((r for r in ahead if r[3] >= 5), None)
            if storm:
                self.tile["storm"].set(time.strftime("%d %b", time.gmtime(storm[0])), t.red,
                                       f"Kp {storm[3]} forecast", led=t.red)
            else:
                self.tile["storm"].set("none", t.main, "no Kp 5+ in the outlook", led=t.main)
            self.issued.setText(f"Issued {d['issued']} (weekly, Mondays). Dashed bars = forecast. A 27-day "
                                "outlook repeats one solar rotation, so recurring coronal holes show up here first.")
        elif key in ("cycle_obs", "cycle_pred"):
            self._draw_cycle()
        elif key == "drap":
            self.drap.set_image(QImage.fromData(d))

    def _draw_cycle(self):
        t = self.t
        obs = self.ctx.hub.data.get("cycle_obs") or []
        pred = self.ctx.hub.data.get("cycle_pred") or []
        now = time.time()
        x0 = now - 17 * 365 * 86400
        obs = [o for o in obs if o[0] >= x0]
        series = []
        if obs:
            series.append(([o[0] for o in obs], [o[1] for o in obs], t.dim, "monthly SSN", False))
            series.append(([o[0] for o in obs], [o[2] for o in obs], t.amber, "13-month smoothed", False))
        bands = []
        if pred:
            series.append(([p[0] for p in pred], [p[1] for p in pred], t.sub, "NOAA prediction", True))
            bands.append(([p[0] for p in pred], [p[2] for p in pred], [p[3] for p in pred], t.sub))
        x1 = max([now + 3 * 365 * 86400] + [p[0] for p in pred[:48]])
        self.cycle.set_data(series, bands, x_range=(x0, x1))
        sm = [o for o in obs if o[2] is not None]
        if sm:
            last = sm[-1]
            peak = max(sm[-8 * 12:], key=lambda o: o[2])
            self.tile["ssn"].set(f"{last[2]:.0f}", t.amber, time.strftime("%b %Y", time.gmtime(last[0])) +
                                 f" · cycle peak {peak[2]:.0f} ({time.strftime('%b %Y', time.gmtime(peak[0]))})",
                                 led=t.main)
            self.cycle_note.setText("Smoothed SSN lags about 6 months. Cycle 25's smoothed peak so far: "
                                    f"{peak[2]:.0f} in {time.strftime('%B %Y', time.gmtime(peak[0]))}. Shaded "
                                    "= NOAA's forecast range.")
        cur = min(pred, key=lambda p: abs(p[0] - now)) if pred else None
        if cur and cur[1] is not None:
            self.tile["pred"].set(f"{cur[1]:.0f}", t.sub, f"F10.7 ≈ {cur[4]:.0f} sfu" if cur[4] else "", led=t.main)

    # ---- imagery -----------------------------------------------------------------------
    def _pick(self, key):
        self.cur_img = key
        url, desc = next((u, d) for k, u, d in IMAGES if k == key)
        self.img_note.setText(desc)
        hit = self.img_cache.get(key)
        if hit:
            self.img.set_image(hit[1])
            self.img.caption = f"{key} · fetched {time.strftime('%H:%Mz', time.gmtime(hit[0]))}"
        if hit and time.time() - hit[0] < 900:
            return
        if not hit:
            self.img.set_image(None, "loading image…")

        def got(data, err, key=key):
            if err or not data:
                if self.cur_img == key and key not in self.img_cache:
                    self.img.set_image(None, f"could not load: {err}")
                return
            img = QImage.fromData(data)
            self.img_cache[key] = (time.time(), img)
            if self.cur_img == key:
                self.img.caption = f"{key} · fetched {time.strftime('%H:%Mz', time.gmtime())}"
                self.img.set_image(img)
        self.ctx.hub.fetch_once(url, lambda raw: raw, got)

    def tick(self):
        hit = self.img_cache.get(self.cur_img)
        if hit and time.time() - hit[0] > 900:
            self._pick(self.cur_img)
