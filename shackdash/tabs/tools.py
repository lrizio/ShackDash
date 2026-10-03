"""N · TOOLS: callsign lookup (country file, LoTW, callook.info for US calls),
the nearest public KiwiSDR receivers (to me or to the DX) and the Australian
licence privileges with a frequency checker."""
from __future__ import annotations

import html
import time
import urllib.parse

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .. import bandplan, locate
from ..geo import bearing_distance, compass, grid_to_latlon
from ..instruments import fill_table, make_table
from ..sources import jload, p_psk
from ..theme import px
from .base import Tab, key_row, note, panel, stretch

US_ADIF = {291, 6, 110, 202, 9, 103, 105, 166, 285, 297, 515}   # USA, Alaska, Hawaii, PR, AS, Guam, ...


class ToolsTab(Tab):
    title = "N · TOOLS"
    keys = ("lotw", "kiwi", "cty")
    footer = ("Country file: AD1C (country-files.com) · LoTW user activity: ARRL · US licence data: callook.info "
              "(FCC ULS) · KiwiSDR list: kiwisdr.com via rx.linkfanel.net · " + bandplan.SOURCE)

    def build(self):
        t = self.t
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.call_in = QLineEdit()
        self.call_in.setPlaceholderText("callsign or grid, e.g. 3Y0K, W1AW, JA1XYZ, IO91wm, then Enter")
        self.call_in.returnPressed.connect(self._lookup)
        go = QPushButton("LOOK UP")
        go.clicked.connect(self._lookup)
        row = QHBoxLayout()
        row.addWidget(self.call_in, 1)
        row.addWidget(go)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setTextFormat(Qt.TextFormat.RichText)
        self.result.setOpenExternalLinks(True)
        self.result.setMinimumHeight(px(150))
        self.result.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.result.setStyleSheet(f"font-size:{px(14)}px; color:{t.text};")
        links = QHBoxLayout()
        self.link_btns = []
        for name in ("QRZ.com", "HamQTH", "Club Log", "PSKReporter map"):
            b = QPushButton(name)
            b.clicked.connect(lambda _c=False, n=name: self._open(n))
            b.setEnabled(False)
            links.addWidget(b)
            self.link_btns.append(b)
        g.addWidget(panel(t, "CALLSIGN LOOKUP", [row, stretch(self.result, 1), links], dot=t.main), 0, 0)

        self.level = self.ctx.cfg.get("licence", "Advanced")
        self.priv = make_table(["BAND", "FROM", "TO", "POWER", "LIMITS"], {0: 60, 1: 100, 2: 100, 3: 220},
                               stretch_col=4)
        self.freq_in = QLineEdit()
        self.freq_in.setPlaceholderText("check a frequency: 7.150, 14074, 146.5 MHz, 10.368 GHz …")
        self.freq_in.textChanged.connect(self._check_freq)
        self.freq_out = note("")
        g.addWidget(panel(t, "MY LICENCE PRIVILEGES  ·  AUSTRALIAN AMATEUR CLASS LICENCE 2023",
                          [key_row(t, list(bandplan.LEVELS), self._pick_level, current=self.level, height=30),
                           stretch(self.priv, 1), self.freq_in, self.freq_out], dot=t.amber), 1, 0)

        self.kiwi_mode = "NEAR ME"
        self.kiwi = make_table(["RECEIVER", "LOCATION", "km", "BRG", "USERS", "MHz", "ANTENNA"],
                               {0: 250, 1: 150, 2: 60, 3: 44, 4: 54, 5: 60}, stretch_col=6)
        self.kiwi.doubleClicked.connect(self._open_kiwi)
        self.kiwi_note = note("")
        g.addWidget(panel(t, "PUBLIC KIWISDR RECEIVERS  ·  HEAR YOURSELF (double-click opens it in the browser)",
                          [key_row(t, ["NEAR ME", "NEAR THE DX", "OPEN SLOTS NEAR DX"], self._pick_kiwi, height=30),
                           stretch(self.kiwi, 1), self.kiwi_note], dot=t.sub), 0, 1, 2, 1)
        g.setColumnStretch(0, 48)
        g.setColumnStretch(1, 52)
        g.setRowStretch(0, 48)
        g.setRowStretch(1, 52)
        self.dx: tuple[float, float, str] | None = None
        self.call = ""
        self._cands: list[tuple] = []
        self._pending: set[str] = set()
        self._lines: list[str] = []
        self._kiwi_rows: list[dict] = []
        self._fill_priv()
        self._check_freq("")
        self.result.setText(f"<span style='color:{t.dim}'>Type a callsign (or a grid locator) and press Enter: "
                            "DXCC entity, zones, local time, LoTW, beam headings, and for US calls the FCC licence "
                            "via callook.info. The KiwiSDR list can then be sorted by distance from that station."
                            "</span>")

    # ---- lookup --------------------------------------------------------------------------------
    def _lookup(self):
        q = self.call_in.text().strip().upper()
        if not q:
            return
        t = self.t
        ll = grid_to_latlon(q) if len(q) in (4, 6, 8) and q[:2].isalpha() and q[2:4].isdigit() else None
        lines = []
        self.call = ""
        self._cands: list[tuple] = []               # (rank, lat, lon, where it came from)
        self._pending: set[str] = set()
        if ll:
            self._cands.append((7, ll[0], ll[1], f"grid locator {q}"))
            lines.append(f"<b style='font-size:{px(20)}px'>{q}</b> &nbsp; grid locator · {ll[0]:.3f}, {ll[1]:.3f}")
        else:
            cty = self.ctx.cty
            ent = cty.lookup(q) if cty else None
            self.call = q
            if not ent:
                self.result.setText(f"<b>{q}</b>: no DXCC entity found (country file "
                                    f"{'not loaded yet' if not cty else 'has no match'}).")
                self.dx = None
                self._fill_kiwi()
                return
            self._cands.append((1, ent.lat, ent.lon, f"centre of {ent.name} (country file)"))
            area = locate.call_area(q, ent.adif)
            if area:
                self._cands.append((2, area[0], area[1], f"call area {area[2]}"))
            cached = locate.from_cached(q, self.ctx.hub.data, self.ctx.aprs)
            if cached:
                self._cands.append(cached)
            if not cached or cached[0] < 6:            # ask PSKReporter for the locator their software sends
                self._pending.add("psk")
                url = ("https://retrieve.pskreporter.info/query?senderCallsign="
                       f"{urllib.parse.quote(locate._base(q)[0])}&flowStartSeconds=-43200&rronly=1")
                self.ctx.hub.fetch_once(url, p_psk, lambda d, e, q=q: self._got_psk(q, d, e))
            pre = cty.main_prefix.get(ent.adif, "")
            off = ent[7]
            local = time.strftime("%H:%M", time.gmtime(time.time() - off * 3600))
            lines.append(f"<b style='font-size:{px(20)}px'>{q}</b> &nbsp; {ent.name} ({pre}) · {ent.cont} · "
                         f"CQ {ent[3]} · ITU {ent[4]} · DXCC {ent.adif}")
            lines.append(f"Local time there about {local} (UTC{-off:+g})")
            lotw = (self.ctx.hub.data.get("lotw") or {}).get(q) or (self.ctx.hub.data.get("lotw") or {}).get(
                q.split("/")[0])
            if self.ctx.hub.data.get("lotw") is None:
                lines.append("LoTW: activity list still loading")
            elif lotw:
                days = (time.time() - time.mktime(time.strptime(lotw, "%Y-%m-%d"))) / 86400
                col = t.main if days < 90 else t.amber if days < 730 else t.dim
                lines.append(f"<span style='color:{col}'>LoTW user · last upload {lotw} ({days:.0f} days ago)</span>")
            else:
                lines.append(f"<span style='color:{t.dim}'>Not in the LoTW user list</span>")
            if ent.adif in US_ADIF:
                self._ask_callook(q)
        self._lines = lines
        for b in self.link_btns:
            b.setEnabled(bool(self.call) or b.text() == "PSKReporter map")
        self._render()

    def _render(self):
        """Info lines + beam headings to the best location found so far, and where it came from."""
        t = self.t
        rank, lat, lon, where = max(self._cands, key=lambda c: c[0])
        self.dx = (lat, lon, self.call or self.call_in.text().strip().upper())
        lat0, lon0 = self.ctx.qth
        brg, km = bearing_distance(lat0, lon0, lat, lon)
        col = t.main if rank >= 4 else t.amber if rank >= 2 else t.red
        quality = ("exact" if rank >= 6 else "locator" if rank == 5 or rank == 7 else "licence address" if rank == 4
                   else "rough: call area" if rank == 2 else "very rough: country centre only")
        lines = list(self._lines)
        lines.append(f"Beam <b>{brg:.0f}° {compass(brg)}</b> short path · {(brg + 180) % 360:.0f}° long path · "
                     f"<b>{km:,.0f} km</b> short / {40030 - km:,.0f} km long")
        lines.append(f"<span style='color:{col}'>Location: {where} · {quality}</span>")
        if self._pending:
            lines.append(f"<i style='color:{t.dim}'>still asking "
                         + " and ".join({"psk": "PSKReporter for their locator", "callook": "callook.info"}[p]
                                        for p in sorted(self._pending)) + "…</i>")
        self.result.setText("<br>".join(lines))
        self._fill_kiwi()

    def _got_psk(self, q, reports, err):
        if q != self.call:
            return
        self._pending.discard("psk")
        hit = locate.psk_locator(reports or [], q) if not err else None
        if hit:
            self._cands.append(hit)
        self._render()

    def _ask_callook(self, q, attempt=1):
        self._pending.add("callook")
        self.ctx.hub.fetch_once(f"https://callook.info/{urllib.parse.quote(locate._base(q)[0])}/json", jload,
                                lambda d, e, q=q: self._got_callook(q, d, e, attempt))

    def _got_callook(self, q, d, err, attempt=1):
        if q != self.call:
            return
        if (err or not d) and attempt == 1:              # callook.info is often slow: one more try
            QTimer.singleShot(2000, lambda: self._ask_callook(q, 2) if q == self.call else None)
            return
        self._pending.discard("callook")
        if err or not d:
            self._lines.append(f"callook.info: {html.escape(err or 'no reply')}")
        elif d.get("status") != "VALID":
            self._lines.append(f"callook.info: {d.get('status', '?').lower()} (not a current FCC licence)")
        else:
            name = d.get("name", "")
            cls = d.get("current", {}).get("operClass", "") or d.get("type", "")
            addr = d.get("address", {}).get("line2", "")
            grid = d.get("location", {}).get("gridsquare", "")
            exp = d.get("otherInfo", {}).get("expiryDate", "")
            self._lines.append(f"<b>{name}</b> · {cls.title()} · {addr} · grid {grid} · expires {exp}")
            loc = d.get("location", {})
            try:
                self._cands.append((4, float(loc["latitude"]), float(loc["longitude"]),
                                    f"FCC licence address, {addr}"))
            except (KeyError, TypeError, ValueError):
                pass
        self._render()

    def _open(self, which):
        c = urllib.parse.quote(self.call.split("/")[0] if which != "PSKReporter map" else self.call)
        url = {"QRZ.com": f"https://www.qrz.com/db/{c}", "HamQTH": f"https://www.hamqth.com/{c}",
               "Club Log": f"https://clublog.org/logsearch/{c}",
               "PSKReporter map": "https://pskreporter.info/pskmap.html?callsign="
                                  + urllib.parse.quote(self.call or self.ctx.call)}[which]
        QDesktopServices.openUrl(QUrl(url))

    # ---- KiwiSDR --------------------------------------------------------------------------------
    def _pick_kiwi(self, m):
        self.kiwi_mode = m
        self._fill_kiwi()

    def _fill_kiwi(self):
        ks = self.ctx.hub.data.get("kiwi") or []
        if not ks:
            return
        if self.kiwi_mode == "NEAR ME" or not self.dx:
            lat, lon, where = *self.ctx.qth, "my QTH"
        else:
            lat, lon, where = self.dx[0], self.dx[1], self.dx[2]
        lat0, lon0 = self.ctx.qth
        rows = []
        best: dict[tuple, dict] = {}                 # one row per site: multi-receiver sites list each Kiwi
        for k in ks:
            key = (round(k["lat"], 2), round(k["lon"], 2), k["antenna"][:20])
            cur = best.get(key)
            if cur is None or k["max"] - k["users"] > cur["max"] - cur["users"]:
                best[key] = k
        for k in best.values():
            _b, km = bearing_distance(lat, lon, k["lat"], k["lon"])
            if self.kiwi_mode == "OPEN SLOTS NEAR DX" and k["users"] >= k["max"]:
                continue
            brg, _km = bearing_distance(lat0, lon0, k["lat"], k["lon"])
            rows.append((km, brg, k))
        rows.sort(key=lambda r: r[0])
        rows = rows[:60]
        self._kiwi_rows = [r[2] for r in rows]
        fill_table(self.kiwi, [(k["name"], k["loc"], f"{km:.0f}", f"{brg:.0f}", f"{k['users']}/{k['max']}",
                                f"{k['lo']:g}-{k['hi']:g}", k["antenna"]) for km, brg, k in rows],
                   [self.t.faint if k["users"] >= k["max"] else None for _km, _b, k in rows], right={2, 3, 4})
        self.kiwi_note.setText(f"{len(ks)} receivers online at {len(best)} sites · sorted by distance from {where} · km is from there, "
                               "BRG is from my QTH · greyed = all slots in use")

    def _open_kiwi(self, idx):
        if idx.row() < len(self._kiwi_rows):
            url = self._kiwi_rows[idx.row()]["url"]
            if url:
                QDesktopServices.openUrl(QUrl(url))

    # ---- privileges ------------------------------------------------------------------------------
    def _pick_level(self, lvl):
        self.level = lvl
        self._fill_priv()
        self._check_freq(self.freq_in.text())

    def _fill_priv(self):
        rows = [(bandplan.band_label(lo), bandplan.fmt_khz(lo), bandplan.fmt_khz(hi), pwr, lim)
                for lo, hi, pwr, lim in bandplan.LEVELS[self.level]]
        fill_table(self.priv, rows)

    def _check_freq(self, text):
        s = text.strip().lower().replace(",", "")
        if not s:
            self.freq_out.setText("pX = peak envelope power, pY = mean power. " + bandplan.SOURCE)
            return
        mult = 1.0
        for unit, m in (("ghz", 1e6), ("mhz", 1e3), ("khz", 1.0)):
            if s.endswith(unit):
                s, mult = s[:-len(unit)].strip(), m
                break
        try:
            v = float(s)
        except ValueError:
            self.freq_out.setText("type a frequency like 7.150 or 14074")
            return
        if mult == 1.0 and not text.lower().strip().endswith("khz"):
            mult = 1e3 if v < 1000 else 1.0                      # bare numbers: MHz below 1000, else kHz
        ok, why = bandplan.check(v * mult, self.level)
        self.freq_out.setText(("✔ " if ok else "✘ ") + f"{bandplan.fmt_khz(v * mult)}: " + why)
        self.freq_out.setStyleSheet(f"color:{self.t.main if ok else self.t.red};")

    def on_data(self, key, d):
        if key == "kiwi":
            self._fill_kiwi()

    def qth_changed(self):
        self._fill_kiwi()
