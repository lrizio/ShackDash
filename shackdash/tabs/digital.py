"""F · DIGITAL VOICE NETWORKS"""
from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLineEdit

from ..extra_sources import HOST_LISTS
from ..instruments import fill_table, make_table
from ..theme import px
from .base import Tab, ago, key_row, note, panel, stretch

NETS = {label: (key, port) for key, label, _f, port in HOST_LISTS}


class DigitalTab(Tab):
    title = "F · DIGITAL"
    keys = ("xlx", "bm_tg", "ysf") + tuple(k for k, *_ in HOST_LISTS)
    footer = ("XLX reflector list (xlxapi.rlx.lu) · BrandMeister API · Pi-Star host files (YSF, D-STAR REF/DCS/XRF, "
              "NXDN, P25; data from DVRef) · double-click an XLX reflector to open its dashboard")

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.q = {"xlx": "Australia", "bm": "Australia", "ysf": "VK", "hosts": ""}
        self.net = HOST_LISTS[0][1]
        self.xlx = make_table(["REFLECTOR", "COUNTRY", "LAST HEARD", "COMMENT"], {0: 90, 1: 160, 2: 86}, stretch_col=3)
        self.xlx.doubleClicked.connect(self._open_xlx)
        self.xlx_note = note("")
        g.addWidget(panel(t, "XLX / D-STAR MULTI-MODE REFLECTORS",
                          [self._search("xlx", "country, reflector or comment"), stretch(self.xlx, 1), self.xlx_note],
                          dot=t.sub), 0, 0)
        self.hosts = make_table(["REFLECTOR", "HOST", "PORT", "MY HOTSPOT"], {0: 100, 1: 260, 2: 60}, stretch_col=3)
        self.hosts_note = note("")
        g.addWidget(panel(t, "D-STAR REF · DCS · XRF · NXDN · P25 REFLECTORS",
                          [key_row(t, list(NETS), self._pick_net, height=30),
                           self._search("hosts", "reflector number or host, e.g. REF023 or 023"),
                           stretch(self.hosts, 1), self.hosts_note], dot=t.amber), 0, 1)
        self.ysf = make_table(["ID", "NAME", "DESCRIPTION", "HOST"], {0: 56, 1: 150, 3: 150}, stretch_col=2)
        self.ysf_note = note("")
        g.addWidget(panel(t, "YSF (FUSION) REFLECTORS", [self._search("ysf", "name or description"),
                                                         stretch(self.ysf, 1), self.ysf_note], dot=t.amber), 1, 0)
        self.bm = make_table(["TALKGROUP", "NAME"], {0: 96}, stretch_col=1)
        g.addWidget(panel(t, "BRANDMEISTER DMR TALKGROUPS",
                          [self._search("bm", "name or number"), stretch(self.bm, 1),
                           note("Live BrandMeister last-heard needs its streaming (socket.io) feed. "
                                "That's parked for the next round.")], dot=t.main), 1, 1)
        g.setColumnStretch(0, 55)
        g.setColumnStretch(1, 45)
        g.setRowStretch(0, 55)
        g.setRowStretch(1, 45)
        self._xlx_rows = []
        self._links_shown: dict = {}

    def _search(self, which, ph):
        e = QLineEdit(self.q[which])
        e.setPlaceholderText(ph)
        e.setClearButtonEnabled(True)
        e.textChanged.connect(lambda s, w=which: self._set(w, s))
        return e

    def _set(self, which, s):
        self.q[which] = s.strip()
        if which == "hosts":
            self._draw_hosts()
            return
        key = {"xlx": "xlx", "bm": "bm_tg", "ysf": "ysf"}[which]
        if key in self.ctx.hub.data:
            self.on_data(key, self.ctx.hub.data[key])

    def _pick_net(self, net):
        self.net = net
        self._draw_hosts()

    def _open_xlx(self, idx):
        i = idx.row()
        if 0 <= i < len(self._xlx_rows) and self._xlx_rows[i]["dashboard"]:
            QDesktopServices.openUrl(QUrl(self._xlx_rows[i]["dashboard"]))

    def _link(self, name: str) -> str:
        return self.ctx.shack_links.get(name.upper(), "")

    def _draw_hosts(self):
        key, default_port = NETS[self.net]
        data = self.ctx.hub.data.get(key)
        src = self.ctx.hub.sources.get(key)
        if data is None:
            fill_table(self.hosts, [])
            self.hosts_note.setText(f"{self.net} list unreachable: {src.error[:90]}" if src and src.error
                                    else f"loading the {self.net} list…")
            return
        q = self.q["hosts"].upper()
        rows, colors = [], []
        linked = [r for r in data if self._link(r["name"])]
        for r in linked + [r for r in data if not self._link(r["name"])]:      # my hotspots' reflectors first
            if q and q not in f"{r['name']} {r['host']}".upper():
                continue
            mine = self._link(r["name"])
            rows.append((r["name"], r["host"], r["port"] or default_port, mine))
            colors.append(self.t.main if mine else None)
        fill_table(self.hosts, rows, colors, right={2})
        self.hosts_note.setText(f"{len(rows)} of {len(data)} {self.net} reflectors · green = one of my hotspots is "
                                "linked to it (tab O) · Pi-Star's lists give the address only, no descriptions")

    def on_data(self, key, d):
        now = time.time()
        if key == "xlx":
            q = self.q["xlx"].upper()
            sel = [r for r in d if not q or q in f"{r['name']} {r['country']} {r['comment']}".upper()]
            sel.sort(key=lambda r: -int(r["lastcontact"] or 0))
            self._xlx_rows = sel
            rows, colors = [], []
            for r in sel:
                lc = int(r["lastcontact"] or 0)
                rows.append((r["name"], r["country"], ago(lc) if lc else "", r["comment"]))
                colors.append(self.t.main if lc and now - lc < 1800 else self.t.dim if not lc or now - lc > 86400
                              else None)
            fill_table(self.xlx, rows, colors)
            self.xlx_note.setText(f"{len(sel)} of {len(d)} reflectors · green = reported in within 30 min")
        elif key == "bm_tg":
            q = self.q["bm"].upper()
            rows = [(tg, name) for tg, name in d if not q or q in f"{tg} {name}".upper()]
            fill_table(self.bm, rows[:2000], right={0})
        elif key == "ysf":
            q = self.q["ysf"].upper()
            rows = []
            for r in d if isinstance(d, list) else []:
                name, desc = r.get("name", ""), r.get("description", "")
                if q and q not in f"{name} {desc}".upper():
                    continue
                rows.append((r["id"], name, desc, r["host"]))
            fill_table(self.ysf, rows)
            self.ysf_note.setText(f"{len(rows)} reflectors")
        elif key == NETS[self.net][0]:
            self._draw_hosts()

    def tick(self):
        src = self.ctx.hub.sources.get("ysf")
        if src and src.error and "ysf" not in self.ctx.hub.data:
            self.ysf_note.setText(f"YSF list unreachable: {src.error[:90]} (retrying every 2 min)")
        if self.ctx.shack_links != self._links_shown:            # tab O polled: re-mark my reflectors
            self._links_shown = dict(self.ctx.shack_links)
            self._draw_hosts()
