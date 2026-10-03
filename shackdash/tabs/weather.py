"""H · WEATHER & SITE SAFETY (Open-Meteo)"""
from __future__ import annotations

import calendar
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from ..geo import compass
from ..instruments import StatTile, TrendPlot, fill_table, make_table
from ..theme import px
from .base import Tab, ago, note, panel, stretch
from .vhf import ImageScreen

WMO = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
       61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
       71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Showers", 81: "Heavy showers",
       82: "Violent showers", 85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm",
       96: "Thunderstorm + hail", 99: "Thunderstorm + hail"}


def _ts(s: str, offset: int) -> float:
    """Open-Meteo local ISO time (no zone) -> epoch."""
    return calendar.timegm(time.strptime(s[:16], "%Y-%m-%dT%H:%M")) - offset


class WeatherTab(Tab):
    title = "H · WEATHER"
    keys = ("weather", "radar", "bom_warn")
    footer = ("Weather data by Open-Meteo.com (CC BY 4.0). The storm risk is a forecast estimate "
              "(weather codes + CAPE), not live lightning detection. Radar and warnings © Commonwealth of Australia, "
              "Bureau of Meteorology.")

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        row = QHBoxLayout()
        row.setSpacing(px(8))
        self.tile = {}
        for k, cap in (("temp", "TEMPERATURE"), ("feels", "FEELS LIKE"), ("hum", "HUMIDITY"), ("wind", "WIND"),
                       ("gust", "GUSTS"), ("press", "PRESSURE"), ("rain", "RAIN NOW"), ("sky", "CONDITIONS")):
            self.tile[k] = StatTile(t, cap)
            row.addWidget(self.tile[k])
        g.addWidget(panel(t, "NOW AT MY QTH", row, dot=t.sub, pad=8), 0, 0, 1, 2)
        alerts = QHBoxLayout()
        alerts.setSpacing(px(8))
        self.tile["walert"] = StatTile(t, "ANTENNA WIND ALERT")
        self.tile["storm"] = StatTile(t, "THUNDERSTORM RISK · 12 h")
        alerts.addWidget(self.tile["walert"])
        alerts.addWidget(self.tile["storm"])
        self.alert_note = note("")
        g.addWidget(panel(t, "SITE SAFETY", [alerts, self.alert_note], dot=t.red, pad=8), 1, 0)
        self.daily = make_table(["DAY", "CONDITIONS", "MIN", "MAX", "RAIN mm", "MAX GUST"],
                                {0: 90, 1: 120, 2: 44, 3: 44, 4: 64}, stretch_col=5)
        g.addWidget(panel(t, "3-DAY OUTLOOK", self.daily, dot=t.amber), 1, 1)
        self.wplot = TrendPlot(t, "km/h", ymin=0, hours=12)
        self.wplot.future_h = 48
        self.tplot = TrendPlot(t, "°C", hours=12)
        self.tplot.future_h = 48
        self.cplot = TrendPlot(t, "", ymin=0, hours=12)
        self.cplot.future_h = 48
        g.addWidget(panel(t, "WIND & GUSTS  ·  12 h BACK, 48 h AHEAD", self.wplot, dot=t.sub), 2, 0)
        g.addWidget(panel(t, "TEMPERATURE", self.tplot, dot=t.amber), 2, 1)
        g.addWidget(panel(t, "STORM FUEL (CAPE J/kg) & RAIN CHANCE %", self.cplot, dot=t.red), 3, 0, 1, 2)
        self.radar = ImageScreen(t)
        self.radar.msg = "loading radar…"
        self.radar_note = note("")
        g.addWidget(panel(t, "BoM RAIN RADAR  ·  LAST HOUR, LOOPING",
                          [stretch(self.radar, 1), self.radar_note], dot=t.sub), 0, 2, 3, 1)
        self.warn = make_table(["ISSUED", "BoM WARNING"], {0: 70}, stretch_col=1)
        g.addWidget(panel(t, "BoM WARNINGS", self.warn, dot=t.red), 3, 2)
        g.setRowStretch(0, 12)
        g.setRowStretch(1, 14)
        g.setRowStretch(2, 26)
        g.setRowStretch(3, 20)
        g.setColumnStretch(0, 30)
        g.setColumnStretch(1, 30)
        g.setColumnStretch(2, 40)
        self.frames: list[tuple[float, QImage]] = []
        self.frame_i = 0
        self.anim = QTimer(self)
        self.anim.timeout.connect(self._step)
        self.anim.start(700)

    def on_data(self, key, d):
        if key == "radar":
            self._radar(d)
            return
        if key == "bom_warn":
            fill_table(self.warn, [(time.strftime("%d %H:%M", time.localtime(w["t"])) if w["t"] else "", w["title"])
                                   for w in d] or [("", "No current warnings")],
                       [self.t.red if "thunderstorm" in w["title"].lower() or "severe" in w["title"].lower()
                        else self.t.amber if "wind" in w["title"].lower() else None for w in d])
            return
        t = self.t
        off = d.get("utc_offset_seconds", 0)
        c = d.get("current", {})
        thr = float(self.ctx.cfg.get("wind_alert_kmh", 60))
        v = lambda k, f="{:.0f}": f.format(c[k]) if c.get(k) is not None else "--"
        self.tile["temp"].set(v("temperature_2m", "{:.1f}") + "°", t.amber, "°C", led=t.main)
        self.tile["feels"].set(v("apparent_temperature", "{:.1f}") + "°", t.amber, "°C")
        self.tile["hum"].set(v("relative_humidity_2m") + "%", t.teal_edge, f"cloud {v('cloud_cover')}%")
        wd = c.get("wind_direction_10m")
        self.tile["wind"].set(v("wind_speed_10m"), t.sub, f"km/h from {compass(wd) if wd is not None else '--'}")
        gust = c.get("wind_gusts_10m") or 0
        self.tile["gust"].set(v("wind_gusts_10m"), t.red if gust >= thr else t.amber if gust >= thr * 0.7 else t.sub,
                              "km/h", led=t.red if gust >= thr else None)
        self.tile["press"].set(v("pressure_msl"), t.teal_edge, "hPa")
        self.tile["rain"].set(v("precipitation", "{:.1f}"), t.sub, "mm")
        code = c.get("weather_code")
        self.tile["sky"].set(WMO.get(code, "--"), t.red if code and code >= 95 else t.text, "")

        h = d.get("hourly", {})
        ts = [_ts(s, off) for s in h.get("time", [])]
        now = time.time()
        self.wplot.levels = [(thr, "ALERT", t.red)]
        self.wplot.set_series([(ts, h.get("wind_speed_10m", []), t.sub, "wind"),
                               (ts, h.get("wind_gusts_10m", []), t.red, "gust")])
        self.tplot.set_series([(ts, h.get("temperature_2m", []), t.amber, "temp")])
        self.cplot.set_series([(ts, h.get("cape", []), t.red, "CAPE"),
                               (ts, [x * 10 if x is not None else None for x in h.get("precipitation_probability", [])],
                                t.sub, "rain% x10")])
        nxt = [(tt, i) for i, tt in enumerate(ts) if now - 3600 <= tt <= now + 12 * 3600]
        gmax = max((h["wind_gusts_10m"][i] or 0 for _, i in nxt), default=0)
        if gust >= thr:
            self.tile["walert"].set("NOW", t.red, f"gusting {gust:.0f} km/h ≥ {thr:.0f}", led=t.red)
        elif gmax >= thr:
            when = next(tt for tt, i in nxt if (h["wind_gusts_10m"][i] or 0) >= thr)
            self.tile["walert"].set("COMING", t.amber, f"{gmax:.0f} km/h by {time.strftime('%H:%M', time.localtime(when))}",
                                    led=t.amber)
        else:
            self.tile["walert"].set("CLEAR", t.main, f"max gust next 12 h {gmax:.0f} km/h", led=t.main)
        storm_codes = [h["weather_code"][i] for _, i in nxt if h["weather_code"][i] in (95, 96, 99)]
        cape = max((h["cape"][i] or 0 for _, i in nxt), default=0)
        pp = max((h["precipitation_probability"][i] or 0 for _, i in nxt), default=0)
        if storm_codes:
            lvl, col, why = "HIGH", t.red, "thunderstorms in the forecast"
        elif cape > 1500 and pp > 40:
            lvl, col, why = "MODERATE", t.amber, f"CAPE {cape:.0f} J/kg with {pp:.0f}% rain chance"
        elif cape > 500:
            lvl, col, why = "LOW", t.amber, f"CAPE up to {cape:.0f} J/kg"
        else:
            lvl, col, why = "MINIMAL", t.main, f"CAPE max {cape:.0f} J/kg"
        self.tile["storm"].set(lvl, col, why, led=col)
        self.alert_note.setText(f"Wind alert threshold {thr:.0f} km/h (change it in SETUP). If a storm is "
                                "likely, disconnect and ground the antennas early.")
        dd = d.get("daily", {})
        rows = []
        for i, day in enumerate(dd.get("time", [])):
            tm = time.strptime(day, "%Y-%m-%d")
            rows.append((time.strftime("%a %d %b", tm), WMO.get(dd["weather_code"][i], ""),
                         f"{dd['temperature_2m_min'][i]:.0f}°", f"{dd['temperature_2m_max'][i]:.0f}°",
                         f"{dd['precipitation_sum'][i]:.1f}", f"{dd['wind_gusts_10m_max'][i]:.0f} km/h"))
        fill_table(self.daily, rows, [t.red if (dd["wind_gusts_10m_max"][i] or 0) >= thr else None
                                      for i in range(len(rows))], right={2, 3, 4})

    # ---- radar ---------------------------------------------------------------------------
    def _radar(self, d):
        layers = {k: QImage.fromData(v) for k, v in d["layers"].items()}
        frames = []
        for ts, png in d["frames"]:
            fr = QImage.fromData(png)
            if fr.isNull():
                continue
            img = QImage(fr.size(), QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0xFF101418)
            p = QPainter(img)
            for k in ("background", "topography"):
                if k in layers and not layers[k].isNull():
                    p.drawImage(0, 0, layers[k])
            p.drawImage(0, 0, fr)
            for k in ("range", "locations"):
                if k in layers and not layers[k].isNull():
                    p.drawImage(0, 0, layers[k])
            p.end()
            frames.append((ts, img))
        self.frames = frames
        self.frame_i = len(frames) - 1
        self._show_frame()

    def _show_frame(self):
        if not self.frames:
            return
        ts, img = self.frames[self.frame_i % len(self.frames)]
        last = self.frames[-1][0]
        self.radar_note.setText(f"Showing {time.strftime('%H:%M', time.localtime(ts))} local"
                                + (" (latest)" if ts == last else "")
                                + f" · radar {self.ctx.cfg.get('bom_radar', 'IDR023')}, {len(self.frames)} frames, "
                                f"newest {ago(last)} old · change the radar in SETUP")
        self.radar.set_image(img)

    def _step(self):
        if self.frames and self.isVisible():
            self.frame_i = (self.frame_i + 1) % (len(self.frames) + 3)       # hold on the latest frame
            if self.frame_i >= len(self.frames):
                return
            self._show_frame()

    def tick(self):
        if int(time.time()) % 60 == 0:
            for p in (self.wplot, self.tplot, self.cplot):
                p.update()
