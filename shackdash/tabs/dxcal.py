"""E · DX & CONTEST CALENDAR"""
from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout

from ..instruments import fill_table, make_table
from ..theme import px
from .base import Tab, hline_search, key_row, note, panel


def span(start, end) -> str:
    if not start:
        return ""
    s = time.strftime("%a %H%Mz", time.gmtime(start))
    if end:
        s += " - " + time.strftime("%a %H%Mz" if end - start < 5 * 86400 else "%d %b", time.gmtime(end))
    return s


def when(start, end, now) -> str:
    if start and end and start <= now <= end:
        left = end - now
        return "ON · " + (f"{left / 3600:.0f}h left" if left < 172800 else f"{left / 86400:.0f}d left")
    if start and start > now:
        d = start - now
        return f"in {d / 3600:.0f}h" if d < 172800 else f"in {d / 86400:.0f}d"
    return "ended" if end and end < now else ""


class DxCalTab(Tab):
    title = "E · DX & CONTESTS"
    keys = ("contests", "dxped", "mostwanted", "cty")
    footer = "WA7BNM Contest Calendar · NG3K Announced DX Operations · Club Log DXCC Most Wanted · double-click to open"

    def build(self):
        t = self.t
        self.c_filter = "NEXT 8 DAYS"
        self.d_filter = "ACTIVE"
        self.mw_search = ""
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        self.contests = make_table(["WHEN", "CONTEST", "UTC"], {0: 96, 2: 150}, stretch_col=1)
        self.contests.doubleClicked.connect(lambda i: self._open(self._c_rows, i.row()))
        g.addWidget(panel(t, "CONTESTS", [key_row(t, ["ON NOW", "NEXT 8 DAYS"], self._pick_c, "NEXT 8 DAYS"),
                                          self.contests], dot=t.amber), 0, 0)
        self.dx = make_table(["STATUS", "ENTITY", "CALL", "DATES", "QSL"], {0: 96, 2: 86, 3: 138, 4: 70},
                             stretch_col=1)
        self.dx.doubleClicked.connect(lambda i: self._open(self._d_rows, i.row()))
        self.dx_note = note("")
        g.addWidget(panel(t, "DXPEDITIONS & DX OPERATIONS", [key_row(t, ["ACTIVE", "UPCOMING", "ALL"], self._pick_d),
                                                             self.dx, self.dx_note], dot=t.purple), 0, 1)
        self.mw = make_table(["RANK", "ENTITY", "CONT", "PREFIX"], {0: 50, 2: 50, 3: 64}, stretch_col=1)
        g.addWidget(panel(t, "DXCC MOST WANTED  ·  CLUB LOG", [hline_search("search entity", self._set_mw), self.mw],
                          dot=t.red), 0, 2)
        g.setColumnStretch(0, 36)
        g.setColumnStretch(1, 40)
        g.setColumnStretch(2, 26)
        self._c_rows, self._d_rows = [], []

    def _open(self, rows, i):
        if 0 <= i < len(rows) and rows[i].get("link"):
            QDesktopServices.openUrl(QUrl(rows[i]["link"]))

    def _pick_c(self, f):
        self.c_filter = f
        self._draw_contests()

    def _pick_d(self, f):
        self.d_filter = f
        self._draw_dx()

    def _set_mw(self, s):
        self.mw_search = s.strip().upper()
        self._draw_mw()

    def on_data(self, key, d):
        if key == "contests":
            self._draw_contests()
        elif key == "dxped":
            self._draw_dx()
        elif key in ("mostwanted", "cty"):
            self._draw_mw()

    def _draw_contests(self):
        now = time.time()
        items = self.ctx.hub.data.get("contests") or []
        sel = []
        for c in items:
            s, e = c["start"], c["end"]
            live = s and e and s <= now <= e
            if self.c_filter == "ON NOW" and not live:
                continue
            if self.c_filter == "NEXT 8 DAYS" and not (live or (s and now < s < now + 8 * 86400)):
                continue
            sel.append(c)
        sel.sort(key=lambda c: c["start"] or 0)
        self._c_rows = sel
        fill_table(self.contests, [(when(c["start"], c["end"], now), c["title"], span(c["start"], c["end"]) or c["desc"])
                                   for c in sel],
                   [self.t.amber if c["start"] and c["start"] <= now <= (c["end"] or 0) else None for c in sel])

    def _draw_dx(self):
        now = time.time()
        items = self.ctx.hub.data.get("dxped") or []
        spotted = {}
        for sp in self.ctx.spots:
            spotted.setdefault(sp["dx"], sp)
        sel = []
        for x in items:
            live = x["start"] and x["start"] <= now <= (x["end"] or 0)
            if self.d_filter == "ACTIVE" and not live:
                continue
            if self.d_filter == "UPCOMING" and not (x["start"] and x["start"] > now):
                continue
            sel.append(x)
        sel.sort(key=lambda x: x["start"] or 0)
        self._d_rows = sel
        rows, colors = [], []
        for x in sel:
            status = when(x["start"], x["end"], now)
            sp = spotted.get(x["call"].upper())
            if sp:
                status = f"SPOTTED {sp['khz']:.0f}"
            rows.append((status, x["entity"], x["call"], x["dates"], x["qsl"]))
            colors.append(self.t.main if sp else self.t.purple if x["start"] and x["start"] <= now else None)
        fill_table(self.dx, rows, colors)
        self.dx_note.setText(f"{len(sel)} shown · green = spotted on the DX cluster this session")

    def _draw_mw(self):
        mw = self.ctx.hub.data.get("mostwanted") or []
        cty = self.ctx.cty
        rows = []
        for rank, adif in mw:
            ent = cty.by_adif.get(adif) if cty else None
            name = ent.name if ent else f"DXCC #{adif}"
            if self.mw_search and self.mw_search not in name.upper():
                continue
            prefix = cty.main_prefix.get(adif, "") if cty else ""
            rows.append((rank, name, ent.cont if ent else "", prefix))
            if len(rows) >= 340:
                break
        fill_table(self.mw, rows, right={0})

    def tick(self):
        if int(time.time()) % 60 == 0:
            self._draw_contests()
            self._draw_dx()
