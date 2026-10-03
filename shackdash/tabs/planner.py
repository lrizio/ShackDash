"""M · PLANNER: things to plan a week or a month ahead: meteor showers (for
meteor scatter), good EME days, ARISS school contacts the ISS will make in
range of the QTH, and ARISS SSTV events."""
from __future__ import annotations

import math
import time

from PySide6.QtWidgets import QGridLayout, QTextBrowser

from .. import astro
from ..instruments import DatePlot, fill_table, make_table
from ..sats import find_passes
from ..theme import px
from .base import Tab, note, panel, stretch

# IMO working-list values (approximate; peaks move by about a day from year to year and are
# found here from the peak solar longitude). Day = daytime shower (radio / meteor scatter only).
SHOWERS = [  # name, code, peak solar longitude, ZHR, radiant RA, Dec, velocity km/s, note
    ("Quadrantids", "QUA", 283.15, 80, 230, 49, 41, "short sharp peak"),
    ("alpha-Centaurids", "ACE", 319.4, 6, 210, -59, 58, "southern"),
    ("Lyrids", "LYR", 32.32, 18, 271, 34, 49, ""),
    ("eta-Aquariids", "ETA", 45.5, 50, 338, -1, 66, "best from the south"),
    ("Daytime Arietids", "ARI", 76.6, 30, 44, 24, 38, "daytime · strong MS shower"),
    ("Daytime zeta-Perseids", "ZPE", 78.6, 20, 62, 23, 29, "daytime · MS"),
    ("Southern delta-Aquariids", "SDA", 127.0, 25, 340, -16, 41, "southern"),
    ("alpha-Capricornids", "CAP", 127.0, 5, 307, -10, 23, "slow fireballs"),
    ("Perseids", "PER", 140.0, 100, 48, 58, 59, "low from VK"),
    ("Daytime Sextantids", "DSX", 184.3, 5, 152, 0, 32, "daytime · MS"),
    ("Draconids", "DRA", 195.4, 10, 262, 54, 20, "variable, northern"),
    ("Southern Taurids", "STA", 197.0, 5, 32, 9, 27, "long, slow"),
    ("Orionids", "ORI", 208.0, 20, 95, 16, 66, ""),
    ("Northern Taurids", "NTA", 230.0, 5, 58, 22, 29, "long, slow"),
    ("Leonids", "LEO", 235.27, 15, 152, 22, 71, "fast"),
    ("Geminids", "GEM", 262.2, 150, 112, 33, 35, "best shower of the year"),
    ("Ursids", "URS", 270.7, 10, 217, 76, 33, "northern only"),
]


def date_of_solar_longitude(lam: float, start: float) -> float:
    """First time after start when the sun reaches ecliptic longitude lam (to ~10 minutes)."""
    cur = astro.sun(start)["lam"]
    t = start + ((lam - cur) % 360) / 0.9856 * 86400
    for _ in range(4):
        diff = (lam - astro.sun(t)["lam"] + 180) % 360 - 180
        t += diff / 0.9856 * 86400
    return t


def radiant_alt(ra: float, dec: float, lat: float, lon: float, ts: float) -> float:
    return astro.alt_az({"ra": ra, "dec": dec, "gmst": astro.gmst_deg(astro.jd(ts))}, lat, lon)[0]


def shower_table(lat: float, lon: float, now: float) -> list[dict]:
    out = []
    for name, code, lam, zhr, ra, dec, v, what in SHOWERS:
        peak = date_of_solar_longitude(lam, now - 3 * 86400)
        day0 = peak - 12 * 3600
        samples = [(day0 + k * 1800, radiant_alt(ra, dec, lat, lon, day0 + k * 1800)) for k in range(48)]
        best_t, best_alt = max(samples, key=lambda s: s[1])
        hours_up = sum(0.5 for _, a in samples if a > 0)
        out.append({"name": name, "code": code, "peak": peak, "zhr": zhr, "v": v, "note": what,
                    "max_alt": best_alt, "best": best_t, "hours": hours_up,
                    "now_alt": radiant_alt(ra, dec, lat, lon, now)})
    out.sort(key=lambda s: s["peak"])
    return out


def eme_days(lat: float, lon: float, start: float, days: int = 28) -> list[dict]:
    out = []
    d0 = astro.local_midnight(start)
    for d in range(days):
        day = d0 + d * 86400
        samples = []
        for k in range(0, 96):
            ts = day + k * 900
            m = astro.moon(ts)
            alt, _az = astro.alt_az(m, lat, lon)
            samples.append((ts, alt, m))
        up = [s for s in samples if s[1] > 5]
        mid = up[len(up) // 2][2] if up else samples[48][2]
        best = max(samples, key=lambda s: s[1])
        s = astro.sun(best[0])
        sep = math.degrees(math.acos(
            math.sin(math.radians(s["dec"])) * math.sin(math.radians(best[2]["dec"])) +
            math.cos(math.radians(s["dec"])) * math.cos(math.radians(best[2]["dec"])) *
            math.cos(math.radians(s["ra"] - best[2]["ra"]))))
        loss = astro.eme_degradation_db(mid["dist_km"])
        hrs = len(up) * 0.25
        score = loss + (3 if sep < 15 else 1 if sep < 30 else 0) + (1.5 if hrs < 6 else 0)
        out.append({"day": day, "dec": mid["dec"], "dist": mid["dist_km"], "loss": loss, "hours": hrs,
                    "max_el": best[1], "sep": sep, "score": score,
                    "rating": "GOOD" if score < 1.0 else "FAIR" if score < 2.2 else "POOR"})
    return out


class PlannerTab(Tab):
    title = "M · PLANNER"
    keys = ("ariss", "sstv", "tle")
    footer = ("Meteor showers: IMO working-list values (approximate) · EME and radiants computed locally · "
              "ARISS contact and SSTV schedules from ariss.org · ISS passes from CelesTrak TLEs")

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.showers = make_table(["SHOWER", "PEAK (UTC)", "IN", "ZHR", "MAX EL", "BEST (LOCAL)", "UP h",
                                   "EL NOW", "km/s", "NOTE"],
                                  {0: 170, 1: 92, 2: 56, 3: 44, 4: 64, 5: 104, 6: 44, 7: 62, 8: 44}, stretch_col=9)
        g.addWidget(panel(t, "METEOR SHOWERS  ·  FOR METEOR SCATTER (6m / 2m) AND WATCHING",
                          [stretch(self.showers, 1), note(
                              "MAX EL = highest radiant elevation at your QTH on the peak day. For meteor scatter the best times "
                              "are when the radiant is 20-50° up. Daytime showers are radio-only and among the best "
                              "MS showers of the year. Highlighted = within 3 days of peak.")], dot=t.purple), 0, 0)
        self.eme_plot = DatePlot(t, "dB")
        self.eme = make_table(["DATE", "RATING", "LOSS", "DEC", "HRS UP", "MAX EL", "SUN SEP",
                               "DISTANCE"], {0: 96, 1: 66, 2: 64, 3: 64, 4: 64, 5: 62, 6: 70}, stretch_col=7)
        g.addWidget(panel(t, "EME PLANNER  ·  NEXT 4 WEEKS FROM MY QTH",
                          [stretch(self.eme_plot, 2), stretch(self.eme, 3), note(
                              "LOSS is the extra path loss over perigee (distance only). Sun separation under 15° "
                              "adds sun noise. More hours with the moon up = longer windows.")], dot=t.amber), 0, 1, 2, 1)
        self.ariss = make_table(["UTC", "LOCAL", "SCHOOL / GROUND STATION", "CREW", "ISS FROM MY QTH"],
                                {0: 96, 1: 96, 2: 360, 3: 150}, stretch_col=4)
        self.ariss_note = note("")
        g.addWidget(panel(t, "ARISS SCHOOL CONTACTS  ·  LISTEN ON 145.800 MHz FM",
                          [stretch(self.ariss, 1), self.ariss_note], dot=t.main), 1, 0)
        self.sstv = QTextBrowser()
        self.sstv.setOpenExternalLinks(True)
        g.addWidget(panel(t, "ARISS SSTV EVENTS  ·  437.550 / 145.800 MHz, ROBOT 36 / PD120", self.sstv, dot=t.sub),
                    2, 0, 1, 2)
        g.setColumnStretch(0, 58)
        g.setColumnStretch(1, 42)
        g.setRowStretch(0, 40)
        g.setRowStretch(1, 32)
        g.setRowStretch(2, 18)
        self._calc_day = None
        self._recalc()

    def _recalc(self):
        lat, lon = self.ctx.qth
        now = time.time()
        self._calc_day = int(now // 3600)
        self.ctx.hub.run(lambda: (shower_table(lat, lon, now), eme_days(lat, lon, now)), self._got)

    def _got(self, res, err):
        if err or not res:
            return
        t = self.t
        showers, eme = res
        now = time.time()
        rows, cols = [], []
        for s in showers:
            dt = s["peak"] - now
            when = f"{dt / 86400:.0f} d" if abs(dt) > 86400 else "TODAY" if dt > -86400 else ""
            rows.append((s["name"], time.strftime("%a %d %b", time.gmtime(s["peak"])), when, s["zhr"],
                         f"{s['max_alt']:.0f}°" if s["max_alt"] > 0 else "never up",
                         time.strftime("%a %H:%M", time.localtime(s["best"])) if s["max_alt"] > 0 else "",
                         f"{s['hours']:.0f}", f"{s['now_alt']:.0f}°", s["v"], s["note"]))
            cols.append(t.main if abs(dt) < 3 * 86400 and s["max_alt"] > 0 else t.faint if s["max_alt"] <= 0
                        else t.amber if 0 < dt < 14 * 86400 else None)
        fill_table(self.showers, rows, cols, right={3, 6, 8})
        erows, ecol = [], []
        for d in eme:
            erows.append((time.strftime("%a %d %b", time.localtime(d["day"])), d["rating"], f"{d['loss']:.1f} dB",
                          f"{d['dec']:+.1f}°", f"{d['hours']:.1f}", f"{d['max_el']:.0f}°", f"{d['sep']:.0f}°",
                          f"{d['dist']:,.0f} km"))
            ecol.append(t.main if d["rating"] == "GOOD" else t.red if d["rating"] == "POOR" else None)
        fill_table(self.eme, erows, ecol, right={2, 3, 4, 5, 6, 7})
        xs = [d["day"] + 43200 for d in eme]
        self.eme_plot.set_data([(xs, [d["loss"] for d in eme], t.amber, "extra path loss dB", False),
                                (xs, [d["hours"] / 4 for d in eme], t.sub, "hours moon up ÷ 4", True)],
                               x_range=(xs[0] - 43200, xs[-1] + 43200))

    def on_data(self, key, d):
        if key in ("ariss", "tle"):
            self._draw_ariss()
        elif key == "sstv":
            html = []
            for ev in d:
                html.append(f"<p><b>{ev['title']}</b><br>" + "<br>".join(ev["lines"][:6]) + "</p>")
            self.sstv.setHtml("".join(html) or "<p>No SSTV events listed.</p>")

    def _draw_ariss(self):
        d = self.ctx.hub.data.get("ariss")
        if not d:
            return
        tle = self.ctx.hub.data.get("tle") or []
        iss = next((s for s in tle if s["norad"] == 25544), None)
        lat, lon = self.ctx.qth
        now = time.time()
        rows, cols = [], []
        for c in d["contacts"]:
            vis = "no TLE yet"
            col = None
            if iss:
                passes = find_passes([iss], lat, lon, 0, start=c["t"] - 900, hours=0.5, step=20)
                p = next((p for p in passes if p["aos"] - 600 <= c["t"] <= p["los"] + 600), None)
                if p:
                    vis = (f"in range: AOS {time.strftime('%H:%M', time.localtime(p['aos']))} local, "
                           f"max {p['max_el']:.0f}°")
                    col = self.t.main
                else:
                    vis = "out of range of my QTH"
            if c["t"] < now - 3600:
                col = self.t.faint
            rows.append((time.strftime("%a %d %H:%M", time.gmtime(c["t"])),
                         time.strftime("%a %d %H:%M", time.localtime(c["t"])), c["desc"], c["crew"], vis))
            cols.append(col)
        fill_table(self.ariss, rows, cols)
        self.ariss_note.setText(f"{d['asof']}. Direct contacts are heard on 145.800 MHz FM wherever the ISS is in "
                                "range of both you and the ground station. Times are ARISS's; your pass check is "
                                "computed from the current TLE.")

    def qth_changed(self):
        self._recalc()
        self._draw_ariss()

    def tick(self):
        if int(time.time() // 3600) != self._calc_day:
            self._recalc()
