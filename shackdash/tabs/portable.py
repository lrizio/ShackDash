"""K · PORTABLE: who is on air from a park or summit right now (POTA, WWFF,
and ParksnPeaks for the VK SOTA/parks scene), merged, filtered and mapped."""
from __future__ import annotations

import re
import time

from PySide6.QtWidgets import QGridLayout, QHBoxLayout

from .. import bandplan
from ..feeds import HF_BANDS, band_of
from ..geo import bearing_distance, compass, gc_points, grid_to_latlon
from ..instruments import StatTile, fill_table, make_table
from ..mapview import MapView
from ..theme import px
from .base import Tab, ago, hline_search, key_row, note, panel, stretch

PROGS = ["ALL", "POTA", "WWFF", "SOTA"]
REGIONS = ["WORLD", "VK", "VK + ZL", "OCEANIA"]
OCEANIA = {"VK", "ZL", "P2", "FK", "YJ", "H4", "3D2", "5W", "A3", "T2", "KH6", "VK9", "E5", "FO", "ZK", "KH2", "V8"}


def _base(call: str) -> str:
    parts = call.split("/")
    return max(parts, key=len) if parts else call


class PortableTab(Tab):
    title = "K · PORTABLE"
    keys = ("pota", "wwff", "pnp", "land", "cty")
    footer = ("Spots: Parks on the Air (api.pota.app) · WWFF Spotline (spots.wwff.co) · ParksnPeaks (parksnpeaks.org). "
              "Refreshed every 2 minutes.")

    def build(self):
        t = self.t
        self.prog, self.region, self.band, self.search = "ALL", "WORLD", "ALL", ""
        self.rows: list[dict] = []
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        self.tile = {}
        for k, cap in (("all", "ACTIVATORS ON AIR"), ("vk", "IN VK"), ("near", "NEAREST TO ME"),
                       ("pota", "POTA"), ("wwff", "WWFF"), ("sota", "SOTA / PnP")):
            self.tile[k] = StatTile(t, cap)
            tiles.addWidget(self.tile[k])
        g.addWidget(panel(t, "ON AIR NOW (spotted in the last 60 minutes)", tiles, dot=t.main, pad=8), 0, 0, 1, 2)

        filt = QHBoxLayout()
        filt.setSpacing(px(12))
        filt.addLayout(key_row(t, PROGS, self._pick_prog, height=30), 4)
        filt.addLayout(key_row(t, REGIONS, self._pick_region, height=30), 4)
        filt.addWidget(hline_search("filter call / ref / park / mode", self._set_search), 3)
        self.table = make_table(["UTC", "AGE", "PROG", "CALL", "MHz", "MODE", "REF", "PARK / SUMMIT", "km", "BRG",
                                 "SPOTTER", "COMMENT"],
                                {0: 46, 1: 42, 2: 70, 3: 88, 4: 70, 5: 44, 6: 88, 7: 190, 8: 52, 9: 40, 10: 76},
                                stretch_col=11)
        self.table.itemSelectionChanged.connect(self._selected)
        self.sel_note = note("Select a spot for its beam heading and whether it is inside your licence privileges.")
        g.addWidget(panel(t, "ACTIVATOR SPOTS", [filt, key_row(t, ["ALL"] + HF_BANDS + ["6m", "VHF+"], self._pick_band,
                                                               height=28), stretch(self.table, 1), self.sel_note],
                          dot=t.main), 1, 0)
        self.map = MapView(t, center_lon=self.ctx.qth[1])
        g.addWidget(panel(t, "WHERE THEY ARE (POTA and WWFF spots carry coordinates)", self.map, dot=t.amber), 1, 1)
        g.setColumnStretch(0, 62)
        g.setColumnStretch(1, 38)
        g.setRowStretch(0, 12)
        g.setRowStretch(1, 88)
        self._sel_path = None

    # ---- data ---------------------------------------------------------------------------------
    def on_data(self, key, d):
        if key == "land":
            self.map.set_land(d)
            return
        self._merge()

    def _merge(self):
        hub = self.ctx.hub.data
        cty = self.ctx.cty
        now = time.time()
        merged: dict[tuple, dict] = {}
        for key in ("pota", "wwff", "pnp"):
            for s in hub.get(key) or []:
                if not s["call"] or not s["t"] or now - s["t"] > 3600:
                    continue
                if s["prog"] == "POTA" and re.search(r"\bQRT\b", s["comment"].upper()):
                    continue
                k = (_base(s["call"]), round((s["khz"] or 0) / 2))
                cur = merged.get(k)
                if cur is None:
                    merged[k] = dict(s, progs=[s["prog"]], refs=[s["ref"]])
                    continue
                if s["prog"] not in cur["progs"]:
                    cur["progs"].append(s["prog"])
                if s["ref"] and s["ref"] not in cur["refs"]:
                    cur["refs"].append(s["ref"])
                if s["t"] > cur["t"]:
                    for f in ("t", "spotter", "comment", "mode"):
                        cur[f] = s[f] or cur[f]
                for f in ("lat", "lon", "name", "grid"):
                    if cur.get(f) in (None, "") and s.get(f):
                        cur[f] = s[f]
        lat, lon = self.ctx.qth
        rows = []
        for s in merged.values():
            if s["lat"] is None and s.get("grid"):
                ll = grid_to_latlon(s["grid"])
                if ll:
                    s["lat"], s["lon"] = ll
            ent = cty.lookup(s["call"]) if cty else None
            s["prefix"] = ""
            if ent and cty:
                s["prefix"] = cty.main_prefix.get(ent.adif, "")
                if s["lat"] is None:
                    s["lat"], s["lon"], s["approx"] = ent.lat, ent.lon, True
            if s["lat"] is not None:
                s["brg"], s["km"] = bearing_distance(lat, lon, s["lat"], s["lon"])
            else:
                s["brg"] = s["km"] = None
            s["band"] = band_of(s["khz"] or 0)
            rows.append(s)
        rows.sort(key=lambda s: s["t"], reverse=True)
        self.rows = rows
        self._draw()

    def _region_ok(self, s) -> bool:
        if self.region == "WORLD":
            return True
        pre = s["prefix"] or ""
        refs = " ".join(s["refs"]).upper()
        vk = pre.startswith("VK") and pre not in ("VK9C", "VK9X", "VK9L", "VK9N", "VK9W", "VK0H", "VK0M") \
            or refs.startswith(("AU-", "VKFF", "VK")) or " VK" in f" {refs}"
        if self.region == "VK":
            return vk
        if self.region == "VK + ZL":
            return vk or pre.startswith("ZL") or refs.startswith(("NZ-", "ZLFF", "ZL"))
        return vk or pre in OCEANIA or pre.startswith(("VK", "ZL", "KH")) or refs.startswith(("AU-", "NZ-", "ZL", "VK"))

    def _band_ok(self, s) -> bool:
        if self.band == "ALL":
            return True
        if self.band == "VHF+":
            return (s["khz"] or 0) >= 60000
        return s["band"] == self.band

    def _visible(self) -> list[dict]:
        out = []
        for s in self.rows:
            progs = "+".join(s["progs"])
            if self.prog == "SOTA" and not any(p not in ("POTA", "WWFF") for p in s["progs"]):
                continue
            if self.prog in ("POTA", "WWFF") and self.prog not in s["progs"]:
                continue
            if not self._region_ok(s) or not self._band_ok(s):
                continue
            if self.search and self.search not in f"{s['call']} {' '.join(s['refs'])} {s['name']} {s['mode']} {progs}".upper():
                continue
            out.append(s)
        return out

    def _draw(self):
        t = self.t
        vis = self._visible()
        self._vis = vis
        now = time.time()
        level = self.ctx.cfg.get("licence", "Advanced")
        rows, colors = [], []
        for s in vis:
            ok, _ = bandplan.check(s["khz"] or 0, level)
            mhz = f"{s['khz'] / 1000:.4f}".rstrip("0").rstrip(".") if s["khz"] else ""
            km = f"{s['km']:.0f}" + ("~" if s.get("approx") else "") if s["km"] is not None else ""
            rows.append((time.strftime("%H:%M", time.gmtime(s["t"])), ago(s["t"]), "+".join(s["progs"]), s["call"],
                         mhz, s["mode"], " ".join(s["refs"]), s["name"], km,
                         f"{s['brg']:.0f}" if s["brg"] is not None else "", s["spotter"], s["comment"]))
            colors.append(t.faint if not ok else t.main if now - s["t"] < 300 else None)
        fill_table(self.table, rows, colors, right={4, 8, 9})
        # tiles
        all_ = self.rows
        vk = [s for s in all_ if (s["prefix"] or "").startswith("VK")]
        self.tile["all"].set(str(len(all_)), t.main, "unique call + frequency", led=t.main)
        self.tile["vk"].set(str(len(vk)), t.amber, "VK activators", led=t.main if vk else None)
        near = min((s for s in all_ if s["km"] is not None and not s.get("approx")), key=lambda s: s["km"], default=None)
        if near:
            self.tile["near"].set(near["call"], t.sub, f"{near['km']:.0f} km · {' '.join(near['refs'])[:24]} · "
                                  f"{(near['khz'] or 0) / 1000:.3f}", led=t.main)
        for k, prog in (("pota", "POTA"), ("wwff", "WWFF")):
            self.tile[k].set(str(sum(1 for s in all_ if prog in s["progs"])), t.teal_edge, "spots in the last hour")
        self.tile["sota"].set(str(sum(1 for s in all_ if any(p not in ("POTA", "WWFF") for p in s["progs"]))),
                              t.purple, "ParksnPeaks")
        # map
        lat, lon = self.ctx.qth
        col = {"POTA": t.main, "WWFF": t.amber}
        markers = [(s["lat"], s["lon"], col.get(s["progs"][0], t.purple), "", 6)
                   for s in vis if s["lat"] is not None and not s.get("approx")]
        markers.append((lat, lon, t.sub, self.ctx.call or "QTH", 12))
        paths = []
        if self._sel_path:
            paths.append(self._sel_path)
        self.map.set_overlays(markers=markers, paths=paths,
                              caption=f"green POTA · amber WWFF · {len(markers) - 1} located · greyed rows are "
                                      f"outside {level} privileges")

    # ---- interaction ------------------------------------------------------------------------
    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(getattr(self, "_vis", [])):
            return
        s = self._vis[rows[0].row()]
        level = self.ctx.cfg.get("licence", "Advanced")
        ok, why = bandplan.check(s["khz"] or 0, level)
        lat, lon = self.ctx.qth
        txt = f"{s['call']} · {' '.join(s['refs'])} {s['name']}"
        if s["brg"] is not None:
            txt += (f" · beam {s['brg']:.0f}° {compass(s['brg'])} (long path {(s['brg'] + 180) % 360:.0f}°), "
                    f"{s['km']:.0f} km" + (" (country centre)" if s.get("approx") else ""))
            self._sel_path = (gc_points(lat, lon, s["lat"], s["lon"], 60), self.t.sub, 1.6, False)
        txt += f" · {level}: " + ("OK, " + why if ok else why)
        self.sel_note.setText(txt)
        self._draw()

    def _pick_prog(self, p):
        self.prog = p
        self._draw()

    def _pick_region(self, r):
        self.region = r
        self._draw()

    def _pick_band(self, b):
        self.band = b
        self._draw()

    def _set_search(self, s):
        self.search = s.strip().upper()
        self._draw()

    def qth_changed(self):
        self.map.set_center(self.ctx.qth[1])
        self._merge()

    def tick(self):
        if int(time.time()) % 30 == 0 and self.rows:
            self._merge()
