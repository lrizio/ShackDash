"""O · MY SHACK: the operator's own LAN gear (hotspots, HF matrix boxes,
clocks...) polled every 30 s. Optional: SETUP can hide this tab, and the
device list is edited here, so another station can list its own gear."""
from __future__ import annotations

import copy
import html
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import config
from ..instruments import StatTile, fill_table, make_table
from ..myshack import TYPE_NAMES, TYPES, BeaconListener, probe_all
from ..theme import px
from ..widgets import Fieldset, Screen
from .base import Tab, ago, note, panel, stretch

POLL_S = 30


def _uptime(s) -> str:
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "?"
    d, h = divmod(s // 3600, 24)
    return f"{d}d {h}h" if d else f"{h}h {s % 3600 // 60}m"


class DeviceCard(Fieldset):
    def __init__(self, t, name):
        super().__init__(t, name, dot=t.faint)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(*self.margins(8))
        scr = Screen(t)
        inner = QVBoxLayout(scr)
        inner.setContentsMargins(px(10), px(6), px(10), px(6))
        self.lbl = QLabel("waiting for the first poll…")
        self.lbl.setTextFormat(Qt.TextFormat.RichText)
        self.lbl.setWordWrap(True)
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.lbl.setStyleSheet(f"font-size:{px(12.5)}px; color:{t.text};")
        inner.addWidget(self.lbl, 1)
        lay.addWidget(scr)


class ShackTab(Tab):
    title = "O · MY SHACK"
    keys = ()
    footer = ("My own LAN gear, polled every 30 s: WPSD hotspots (m5status.php), HF Matrix boxes (/api/status + UDP "
              "discovery beacon), anything else by web page or ping. Hide this tab in SETUP.")

    def build(self):
        t = self.t
        self.beacons = BeaconListener()
        self.results: list[dict] = []
        self.g = g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        tiles = QHBoxLayout()
        tiles.setSpacing(px(8))
        self.tile = {}
        for k, cap in (("up", "DEVICES UP"), ("hs", "HOTSPOTS LINKED"), ("mx", "MATRIX BOXES"),
                       ("temp", "HOTTEST PI"), ("last", "LAST HEARD"), ("poll", "LAST POLL")):
            self.tile[k] = StatTile(t, cap)
            tiles.addWidget(self.tile[k])
        btns = QVBoxLayout()
        for text, fn in (("POLL NOW", self.poll), ("EDIT DEVICES", self.edit)):
            b = QPushButton(text)
            b.setMinimumWidth(px(130))
            b.clicked.connect(fn)
            btns.addWidget(b)
        tiles.addLayout(btns)
        g.addWidget(panel(t, "MY SHACK", tiles, dot=t.main, pad=8), 0, 0)
        self.cards_host = QWidget()
        self.cards = QGridLayout(self.cards_host)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setHorizontalSpacing(px(10))
        self.cards.setVerticalSpacing(px(8))
        g.addWidget(self.cards_host, 1, 0)
        self.heard = make_table(["UTC", "LOCAL", "HOTSPOT", "CALL", "SUFFIX", "TO", "SRC", "SECS", "BER %"],
                                {0: 60, 1: 60, 2: 110, 3: 100, 4: 70, 5: 170, 6: 50, 7: 54}, stretch_col=8)
        g.addWidget(panel(t, "LAST HEARD ACROSS MY HOTSPOTS", self.heard, dot=t.amber), 2, 0)
        g.setRowStretch(0, 12)
        g.setRowStretch(1, 52)
        g.setRowStretch(2, 36)
        self.card_w: list[DeviceCard] = []
        self._make_cards()
        self._busy = False
        self._last_poll = 0.0

    @property
    def devices(self) -> list[dict]:
        cfg = self.ctx.cfg
        if "shack_devices" not in cfg:
            cfg["shack_devices"] = []                    # a new station starts empty and adds its own gear
        if cfg.get("shack_devices_rev", 1) < 2:           # 2026-09-28: clock got /status, OLED clock retired
            devs = [d for d in cfg["shack_devices"] if d.get("host") != "shackclock-oled.local"]
            for d in devs:
                if d.get("host") == "shackclock.local" and d.get("type") == "ping":
                    d["type"] = "clock"
            cfg["shack_devices"] = devs
            cfg["shack_devices_rev"] = 2
        return cfg["shack_devices"]

    def _make_cards(self):
        for c in self.card_w:
            c.setParent(None)
            c.deleteLater()
        self.card_w = []
        n = len(self.devices)
        cols = 5 if n > 8 else 4 if n > 6 else max(1, min(n, 3))
        for i, d in enumerate(self.devices):
            c = DeviceCard(self.t, d.get("name", "?"))
            self.cards.addWidget(c, i // cols, i % cols)
            self.card_w.append(c)
        for r in range((n + cols - 1) // cols):
            self.cards.setRowStretch(r, 1)
        for k in range(cols):
            self.cards.setColumnStretch(k, 1)
        if not n:
            lb = note("No devices yet. Use EDIT DEVICES to add your hotspots, switches and other LAN gear. A hotspot "
                      "needs m5status.php first: run hotspot\\install_hotspot.bat.")
            self.cards.addWidget(lb, 0, 0)

    # ---- polling ------------------------------------------------------------------------------
    def poll(self):
        if self._busy:
            return
        self._busy = True
        self._last_poll = time.time()
        devs = copy.deepcopy(self.devices)
        self.ctx.hub.run(lambda: probe_all(devs, self.beacons), self._got)

    def _got(self, res, err):
        self._busy = False
        if err or res is None:
            self.tile["poll"].set("ERROR", self.t.red, err[:40])
            return
        self.results = res
        changed = False
        for d, r in zip(self.devices, res):             # remember where each device answered
            if r["up"] and r["ip"] and r["ip"] != d.get("ip"):
                d["ip"] = r["ip"]
                changed = True
            if r.get("mon_name"):                       # renamed on the Hotspot Monitor: keep the new name
                d["mon_name"] = r["mon_name"]
                d["name"] = r["name"]
                changed = True
        if changed:
            config.save(self.ctx.cfg)
        self._draw()

    def _draw(self):
        t = self.t
        res = self.results
        heard = []
        for card, r in zip(self.card_w, res):
            col = t.main if r["up"] else t.amber if r["ms"] is not None else t.red
            lines = []
            where = f"{r['ip'] or 'no address'} · {r['how']}"
            if r["ms"] is not None:
                where += f" · {r['ms']:.0f} ms"
            lines.append(f"<span style='color:{t.dim}'>{TYPE_NAMES.get(r['type'], r['type'])} · {where}</span>")
            d = r["data"]
            if r["error"]:
                lines.append(f"<span style='color:{col}'>{html.escape(r['error'])}</span>")
            if r["type"] == "wpsd" and d:
                link = d.get("link") or {}
                st = link.get("state", "?")
                lcol = t.main if st == "linked" else t.amber
                lines.append(f"<b style='color:{lcol}'>{html.escape(str(link.get('target') or st))}</b>"
                             + (f" <span style='color:{t.dim}'>· {ago(link.get('since'))}</span>"
                                if link.get("since") else ""))
                tc = d.get("cpu_temp")
                tcol = t.main if (tc or 0) < 65 else t.amber if (tc or 0) < 75 else t.red
                lines.append(f"CPU <span style='color:{tcol}'>{tc}°C</span> · load {d.get('load')} · up "
                             f"{_uptime(d.get('uptime'))}" + ("" if d.get("mmdvm_running", True) else
                                                               f" · <b style='color:{t.red}'>MMDVM STOPPED</b>"))
                lh = d.get("lastheard") or []
                if lh:
                    x = lh[0]
                    lines.append(f"last: <b>{html.escape(x.get('call', ''))}</b> {ago(x.get('time'))} ago → "
                                 f"{html.escape(str(x.get('to', '')))}")
                for x in lh[:12]:
                    heard.append((x.get("time") or 0, r["name"], x))
            elif r["type"] == "matrix" and d:
                ants = d.get("antennas") or []
                for rad in d.get("radios") or []:
                    a = rad.get("antenna", -1)
                    aname = ants[a]["name"] if 0 <= a < len(ants) else "—"
                    flag = (f" <b style='color:{t.red}'>FAULT</b>" if rad.get("fault") else
                            f" <span style='color:{t.amber}'>switching</span>" if rad.get("switching") else "")
                    lines.append(f"{html.escape(rad.get('name', '?'))} → <b style='color:"
                                 f"{t.main if a >= 0 else t.dim}'>{html.escape(aname)}</b>{flag}")
                extra = []
                for k, lab in (("loadTempC", "load"), ("heatsinkTempC", "heatsink")):
                    if d.get(k) is not None:
                        extra.append(f"{lab} {d[k]:.1f}°C")
                if d.get("supplyV") is not None:
                    extra.append(f"{d['supplyV']:.1f} V")
                if extra:
                    lines.append(f"<span style='color:{t.dim}'>{' · '.join(extra)}</span>")
                if d.get("alarm") or d.get("i2cAlarm"):
                    col = t.red
                    lines.append(f"<b style='color:{t.red}'>ALARM: {html.escape(d.get('alarm') or 'I2C bus')}</b>")
            elif r["type"] == "clock" and d:
                if d.get("synced"):
                    age = d.get("sync_age", 0)
                    scol = t.amber if d.get("sync_stale") else t.main
                    lines.append(f"<b style='color:{scol}'>NTP synced {ago(time.time() - age)} ago</b> "
                                 f"<span style='color:{t.dim}'>· {d.get('syncs')} syncs · "
                                 f"{html.escape(str(d.get('ntp', '')))}</span>")
                else:
                    col = t.amber
                    lines.append(f"<b style='color:{t.amber}'>waiting for NTP time sync</b>")
                rssi = d.get("rssi", 0)
                rcol = t.main if rssi > -67 else t.amber if rssi > -78 else t.red
                lines.append(f"{html.escape(str(d.get('zone', '')))} · brightness {d.get('dim', '?')} · WiFi "
                             f"<span style='color:{rcol}'>{rssi} dBm</span>")
                lines.append(f"<span style='color:{t.dim}'>up {_uptime(d.get('uptime'))} · "
                             f"{d.get('wifi_connects', 0)} WiFi connects · heap {d.get('heap', 0) // 1024} kB</span>")
            elif r["type"] == "hotspotmon" and d:
                for h in d.get("hotspots") or []:
                    hcol = t.main if h.get("online") else t.red
                    lines.append(f"<span style='color:{hcol}'>●</span> {html.escape(str(h.get('name', '?')))} "
                                 f"<span style='color:{t.dim}'>· {html.escape(str(h.get('mdns') or h.get('ip') or ''))}"
                                 "</span>")
            card.set_title(r["name"], dot=col, edge=col if not r["up"] else None)
            card.lbl.setText("<br>".join(lines))
        # tiles
        up = sum(1 for r in res if r["up"])
        self.tile["up"].set(f"{up}/{len(res)}", t.main if up == len(res) else t.amber if up else t.red,
                            ", ".join(r["name"] for r in res if not r["up"])[:48] or "all answering",
                            led=t.main if up == len(res) else t.amber)
        hs = [r for r in res if r["type"] == "wpsd"]
        linked = [r for r in hs if r["data"] and (r["data"].get("link") or {}).get("state") == "linked"]
        self.tile["hs"].set(f"{len(linked)}/{len(hs)}", t.main if len(linked) == len(hs) else t.amber,
                            "linked to a reflector / network", led=t.main if hs else None)
        mx = [r for r in res if r["type"] == "matrix"]
        alarms = [r for r in mx if r["data"] and (r["data"].get("alarm") or r["data"].get("i2cAlarm"))]
        self.tile["mx"].set(f"{sum(1 for r in mx if r['up'])}/{len(mx)}", t.red if alarms else t.main,
                            "ALARM on " + ", ".join(r["name"] for r in alarms) if alarms else "up · no alarms",
                            led=t.red if alarms else t.main if mx else None)
        temps = [(r["data"].get("cpu_temp"), r["name"]) for r in hs if r["data"] and r["data"].get("cpu_temp")]
        if temps:
            tc, who = max(temps)
            self.tile["temp"].set(f"{tc:.0f}°C", t.main if tc < 65 else t.amber if tc < 75 else t.red, who)
        links = {}                                   # for tab F: which reflectors my hotspots are on
        for r in res:
            if r["type"] == "wpsd" and r["data"]:
                link = r["data"].get("link") or {}
                target = str(link.get("target") or "").upper()
                if link.get("state") == "linked" and target:
                    links[target.split()[0]] = f"{r['name']} ({target})"
        self.ctx.shack_links = links
        heard.sort(key=lambda h: h[0], reverse=True)
        if heard:
            ts, who, x = heard[0]
            self.tile["last"].set(x.get("call", ""), t.amber, f"{ago(ts)} ago on {who}", led=t.main)
        self.tile["poll"].set(time.strftime("%H:%M:%S"), t.sub, f"every {POLL_S} s · {len(self.beacons.seen)} "
                              "matrix beacon(s) heard")
        rows, cols = [], []
        for ts, who, x in heard[:120]:
            ber = x.get("ber")
            rows.append((time.strftime("%H:%M:%S", time.gmtime(ts)), time.strftime("%H:%M", time.localtime(ts)), who,
                         x.get("call", ""), x.get("sfx", ""), x.get("to", ""), x.get("src", ""),
                         "" if x.get("dur") is None else f"{x['dur']:.1f}", "" if ber is None else f"{ber:g}"))
            cols.append(t.amber if x.get("src") == "RF" else t.main if time.time() - ts < 300 else None)
        fill_table(self.heard, rows, cols, right={7, 8})

    def tick(self):
        pass

    def background_tick(self):
        """Called every second by the window even when this tab is hidden."""
        if time.time() - self._last_poll >= POLL_S:
            self.poll()

    # ---- editing -------------------------------------------------------------------------------
    def edit(self):
        dlg = DeviceEditor(self, copy.deepcopy(self.devices))
        if dlg.exec():
            self.ctx.cfg["shack_devices"] = dlg.devices()
            config.save(self.ctx.cfg)
            self.results = []
            self._make_cards()
            self.poll()


class DeviceEditor(QDialog):
    def __init__(self, tab: ShackTab, devices: list[dict]):
        super().__init__(tab)
        self.setWindowTitle("My Shack devices")
        self.resize(px(900), px(520))
        t = tab.t
        self.tb = QTableWidget(0, 4)
        self.tb.setHorizontalHeaderLabels(["NAME", "TYPE", "HOST (name.local, name or IP)", "LAST ADDRESS"])
        self.tb.verticalHeader().setVisible(False)
        h = self.tb.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for d in devices:
            self._add(d)
        lay = QVBoxLayout(self)
        lay.addWidget(panel(t, "DEVICES", [self.tb, note(
            "Types: WPSD hotspot = WPSD or Pi-Star with m5status.php (install it with "
            "hotspot\\install_hotspot.bat) · HF matrix box = /api/status (also found by its UDP "
            "beacon, so its host is just the hostname, e.g. hfmatrix2) · Shack Clock = its /status page · Hotspot Monitor = the Nextion monitor (hotspotmon-nx.local); a hotspot renamed on its touch keyboard is renamed here too (a name typed here stays until the next rename there) · web device = up/down by its web page · "
            "LAN device = ping. LAST ADDRESS fills itself in and is used when the name stops resolving.")],
                            dot=t.main))
        row = QHBoxLayout()
        for text, fn in (("ADD", lambda: self._add({"name": "New device", "type": "ping", "host": "", "ip": ""})),
                         ("REMOVE", self._remove), ("UP", lambda: self._move(-1)), ("DOWN", lambda: self._move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        for text, fn in (("CANCEL", self.reject), ("SAVE", self.accept)):
            b = QPushButton(text)
            b.setMinimumWidth(px(110))
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)

    def _add(self, d):
        r = self.tb.rowCount()
        self.tb.insertRow(r)
        item = QTableWidgetItem(d.get("name", ""))
        item.setData(Qt.ItemDataRole.UserRole, d.get("mon_name"))   # kept so a manual rename sticks
        self.tb.setItem(r, 0, item)
        cb = QComboBox()
        for k in TYPES:
            cb.addItem(TYPE_NAMES[k], k)
        cb.setCurrentIndex(max(0, cb.findData(d.get("type", "ping"))))
        self.tb.setCellWidget(r, 1, cb)
        self.tb.setItem(r, 2, QTableWidgetItem(d.get("host", "")))
        self.tb.setItem(r, 3, QTableWidgetItem(d.get("ip", "")))

    def _remove(self):
        r = self.tb.currentRow()
        if r >= 0:
            self.tb.removeRow(r)

    def _move(self, step):
        r = self.tb.currentRow()
        devs = self.devices()
        k = r + step
        if 0 <= r < len(devs) and 0 <= k < len(devs):
            devs[r], devs[k] = devs[k], devs[r]
            self.tb.setRowCount(0)
            for d in devs:
                self._add(d)
            self.tb.selectRow(k)

    def devices(self) -> list[dict]:
        out = []
        for r in range(self.tb.rowCount()):
            txt = lambda c: (self.tb.item(r, c).text().strip() if self.tb.item(r, c) else "")
            name = txt(0)
            if not name:
                continue
            d = {"name": name, "type": self.tb.cellWidget(r, 1).currentData(), "host": txt(2), "ip": txt(3)}
            mon = self.tb.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if mon:
                d["mon_name"] = mon
            out.append(d)
        return out
