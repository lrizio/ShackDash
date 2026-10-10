"""The dashboard window: frameless, family 3D look, a row of 3D tab keys
(A-I), the pages, and a footer with attribution and source health."""
from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizeGrip, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget, QComboBox, QDoubleSpinBox)

from . import config, extra_sources, sources
from .aprs import AprsFeed
from .bandplan import LEVELS
from .extra_sources import BOM_STATES
from .feeds import TelnetFeed
from .geo import grid_to_latlon
from .instruments import fill_table, make_table
from .net import Hub
from .updatecheck import PAGE_URL, UpdateChecker
from .tabs.base import Ctx, ago, note, panel
from .tabs.aprs_tab import AprsTab
from .tabs.dxcal import DxCalTab
from .tabs.digital import DigitalTab
from .tabs.live import LiveTab
from .tabs.local import LocalTab
from .tabs.news import NewsTab
from .tabs.planner import PlannerTab
from .tabs.portable import PortableTab
from .tabs.satellites import SatTab
from .tabs.shack import ShackTab
from .tabs.space import SpaceTab
from .tabs.sun import SunTab
from .tabs.tools import ToolsTab
from .tabs.vhf import VhfTab
from .tabs.weather import WeatherTab
from .theme import DESIGN_H, DESIGN_W, THEMES, px, set_scale, stylesheet, theme_by_name
from .widgets import DeckButton, LedLabel

TABS = [(SpaceTab, "A · SPACE WX"), (LiveTab, "B · LIVE"), (LocalTab, "C · LOCAL"), (SatTab, "D · SATS"),
        (DxCalTab, "E · DX & CONTESTS"), (DigitalTab, "F · DIGITAL"), (VhfTab, "G · VHF/UHF"),
        (WeatherTab, "H · WEATHER"), (NewsTab, "I · NEWS"), (SunTab, "J · SUN"), (PortableTab, "K · PORTABLE"),
        (AprsTab, "L · APRS"), (PlannerTab, "M · PLANNER"), (ToolsTab, "N · TOOLS"), (ShackTab, "O · MY SHACK")]

DEFERRED = [
    ("BoM Australian Space Weather (T-index, HF fadeouts)", "free API key needed", "A"),
    ("aprs.fi (history of my own beacons)", "free API key needed; L shows live APRS-IS instead", "L"),
    ("QRZ.com / HamQTH callsign data", "account needed; N links to their pages instead", "N"),
    ("SOTAwatch spots (SOTA API)", "its terms need prior approval for apps like this; K gets SOTA spots "
     "via ParksnPeaks", "K"),
    ("VK callsign holder lookup", "not in the ACMA register data since the 2024 class licence", "N"),
    ("Blitzortung live lightning", "licence limits redistribution; H shows a forecast storm risk instead", "H"),
    ("BrandMeister last-heard", "streaming socket.io feed, still to be worked out", "F"),
    ("AMSAT satellite status reports", "the public API returned no data when tested", "D"),
]


_EDGE = 5          # px of window border that grabs the mouse for resizing


class DragBar(QFrame):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self._off: QPoint | None = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not (self.win.isFullScreen() or self.win.isMaximized()):
            self._off = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._off is not None:
            self.win.move(e.globalPosition().toPoint() - self._off)

    def mouseReleaseEvent(self, _):
        self._off = None

    def mouseDoubleClickEvent(self, _):
        self.win.toggle_max()


class DashWindow(QWidget):
    def __init__(self, cfg: dict, icon=None):
        super().__init__()
        self.cfg = cfg
        self.setWindowTitle(config.APP_TITLE)
        if icon:
            self.setWindowIcon(icon)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.hub = Hub(self)
        for s in sources.build(cfg) + extra_sources.build(cfg):
            self.hub.add(s)
        self.ctx = Ctx(cfg, self.hub)
        self.hub.updated.connect(self._on_data)
        self.feeds: dict[str, TelnetFeed] = {}
        self.tabs: list = []
        self.root: QWidget | None = None
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(*(_EDGE,) * 4)      # thin border strip = the resize handle
        self._outer.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)   # allow shrinking below the layout hint
        self.setMinimumSize(px(900), px(560))
        self.setMouseTracking(True)
        self._sources_dlg = None
        self._update: tuple[str, str] | None = None
        self._normal_geo: QRect | None = None
        self.build_ui()
        self._restore_geometry()
        self.hub.start()
        self.start_feeds()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        if not cfg.get("qth_confirmed") and not cfg.get("_load_failed"):
            QTimer.singleShot(700, self.show_setup)         # first start: ask for call + QTH straight away
        if cfg.get("check_updates", True):                   # one quiet look at GitHub a few seconds after start
            self.updater = UpdateChecker(self)
            self.updater.found.connect(self._update_found)
            QTimer.singleShot(4000, self.updater.start)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_full)
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.isFullScreen() and self.toggle_full())
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.hub.refresh_all)
        for i in range(10):
            QShortcut(QKeySequence(str((i + 1) % 10)), self, activated=lambda i=i: self.show_tab(i))
        for i in range(len(TABS)):                          # tab letters A.. : Alt+letter, and Ctrl+letter too
            letter = chr(ord("A") + i)                      # (Ctrl+A / Ctrl+C stay select-all / copy)
            QShortcut(QKeySequence(f"Alt+{letter}"), self, activated=lambda i=i: self.show_tab(i))
            if letter not in "AC":
                QShortcut(QKeySequence(f"Ctrl+{letter}"), self, activated=lambda i=i: self.show_tab(i))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.show_tab((self.cur + 1) % len(self.tabs)))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self,
                  activated=lambda: self.show_tab((self.cur - 1) % len(self.tabs)))

    # ---- build ------------------------------------------------------------------------
    def build_ui(self):
        z = float(self.cfg.get("zoom", 1.0))
        set_scale(z)
        self.t = theme_by_name(self.cfg.get("theme", "SHACK"))
        self.ctx.t = self.t
        QApplication.instance().setStyleSheet(stylesheet(self.t))
        if self.root is not None:
            self._stop_tab_threads()
            self.root.setParent(None)
            self.root.deleteLater()
        t = self.t
        self.root = QWidget()
        self.root.setCursor(Qt.CursorShape.ArrowCursor)    # else children inherit the window's edge-resize cursor
        self._outer.addWidget(self.root)
        v = QVBoxLayout(self.root)
        v.setContentsMargins(px(14), px(4), px(14), px(4))
        v.setSpacing(px(8))

        bar = DragBar(self)
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(px(6), px(4), 0, 0)
        hb.setSpacing(px(8))
        title = QLabel(f"{config.APP_NAME} v{config.VERSION}")
        title.setObjectName("title")
        hb.addWidget(title)
        self.station = QLabel("")
        self.station.setStyleSheet(f"color:{t.dim}; font-size:{px(13)}px; font-weight:600; letter-spacing:1px;")
        hb.addSpacing(px(12))
        hb.addWidget(self.station)
        hb.addStretch(1)
        self.clock = QLabel("")
        self.clock.setStyleSheet(f"font-family:Bahnschrift; font-size:{px(20)}px; font-weight:600; color:{t.main};")
        hb.addWidget(self.clock)
        hb.addSpacing(px(14))
        self.update_btn = QPushButton("")
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.setStyleSheet(f"color:{t.amber}; font-weight:700;")
        self.update_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._update[1] if self._update else PAGE_URL)))
        hb.addWidget(self.update_btn)
        self._show_update()
        self.net_led = LedLabel(t, "DATA")
        self.net_led.setMinimumWidth(px(230))
        self.net_led.setCursor(Qt.CursorShape.PointingHandCursor)
        self.net_led.mousePressEvent = lambda _e: self.show_sources()
        hb.addWidget(self.net_led)
        for text, fn in (("REFRESH", self.hub.refresh_all), ("SOURCES", self.show_sources), ("THEME", self.next_theme),
                         ("SETUP", self.show_setup), ("–", self.showMinimized), ("▢", self.toggle_max),
                         ("CLOSE", self.close)):
            b = QPushButton(text)
            b.setMinimumWidth(px(40 if len(text) == 1 else 88))
            b.clicked.connect(fn)
            hb.addWidget(b)
        v.addWidget(bar)

        tabs = [(c, lab) for c, lab in TABS if c is not ShackTab or self.cfg.get("show_myshack", True)]
        per_row = (len(tabs) + 1) // 2
        self.tab_keys = []
        for start in (0, per_row):
            keys = QHBoxLayout()
            keys.setSpacing(px(8))
            for i, (_cls, lab) in enumerate(tabs[start:start + per_row], start):
                b = DeckButton(t, lab, led=True)
                b.setMinimumHeight(px(36))
                b.setMaximumHeight(px(40))
                b.clicked.connect(lambda i=i: self.show_tab(i))
                keys.addWidget(b, 3 if len(lab) > 12 else 2)
                self.tab_keys.append(b)
            if start and len(tabs) % 2:
                keys.addStretch(2)                     # odd count: keep the second row's keys the same size
            v.addLayout(keys)

        self.stack = QStackedWidget()
        self.tabs = [cls(self.ctx) for cls, _lab in tabs]
        for tab in self.tabs:
            self.stack.addWidget(tab)
        v.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("footer")
        self.footer.setWordWrap(False)
        self.footer.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # never widens the window
        foot.addWidget(self.footer, 1)
        grip = QSizeGrip(self.root)
        foot.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        v.addLayout(foot)
        self.cur = -1
        self.show_tab(int(self.cfg.get("tab", 0)))
        self._update_station()

    def _update_found(self, version: str, url: str):
        self._update = (version, url)
        self._show_update()

    def _show_update(self):
        self.update_btn.setVisible(self._update is not None)
        if self._update:
            self.update_btn.setText(f"UPDATE v{self._update[0]} AVAILABLE")
            self.update_btn.setToolTip("A newer ShackDash is on GitHub. Click to open the download page.")

    def _update_station(self):
        lat, lon = self.ctx.qth
        warn = "" if self.cfg.get("qth_confirmed") else "   ·   set your QTH in SETUP"
        if self.cfg.get("_load_failed"):
            warn = "   ·   SETTINGS FILE UNREADABLE - restart ShackDash (nothing will be saved)"
        self.station.setText(f"{self.ctx.call or 'NO CALL'}  ·  {self.cfg.get('grid') or 'NO QTH'}  ·  "
                             f"{lat:.2f}, {lon:.2f}{warn}")

    def show_tab(self, i: int):
        i = max(0, min(len(self.tabs) - 1, i))
        self.cur = i
        self.cfg["tab"] = i
        self.stack.setCurrentIndex(i)
        for k, b in enumerate(self.tab_keys):
            b.set_state(active=(k == i), selected=(k == i))
        self.footer.setText(self.tabs[i].footer)
        self.tabs[i].tick()

    # ---- window ---------------------------------------------------------------------------
    def _edges_at(self, pos) -> Qt.Edge:
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        m = _EDGE + 3
        e = Qt.Edge(0)
        if pos.x() < m:
            e |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - m:
            e |= Qt.Edge.RightEdge
        if pos.y() < m:
            e |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - m:
            e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, e):
        ed = self._edges_at(e.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if ed in (L | T, R | B):
            cur = Qt.CursorShape.SizeFDiagCursor
        elif ed in (R | T, L | B):
            cur = Qt.CursorShape.SizeBDiagCursor
        elif ed in (L, R):
            cur = Qt.CursorShape.SizeHorCursor
        elif ed in (T, B):
            cur = Qt.CursorShape.SizeVerCursor
        else:
            cur = Qt.CursorShape.ArrowCursor
        self.setCursor(cur)

    def leaveEvent(self, e):
        self.unsetCursor()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        ed = self._edges_at(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and ed and self.windowHandle():
            self.windowHandle().startSystemResize(ed)

    def _restore_geometry(self):
        geo = self.cfg.get("geometry")
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        if geo and len(geo) == 4:
            x, y, w, h = geo
            want = QRect(x, y, w, h)
            if any(s.availableGeometry().intersects(want) for s in QGuiApplication.screens()):  # any monitor
                self.setGeometry(x, y, max(900, w), max(600, h))
                self._normal_geo = self.geometry()
                return
        w = min(px(DESIGN_W), int(scr.width() * 0.96))
        h = min(px(DESIGN_H), int(scr.height() * 0.94))
        self.setGeometry(scr.x() + (scr.width() - w) // 2, scr.y() + (scr.height() - h) // 2, w, h)
        self._normal_geo = self.geometry()

    # A frameless window's showNormal() after full screen -> maximised lands back on the big size, so the
    # normal size is remembered here and put back explicitly.
    def _remember_normal(self):
        if not (self.isMaximized() or self.isFullScreen()):
            self._normal_geo = self.geometry()

    def _go_normal(self):
        self.setWindowState(Qt.WindowState.WindowNoState)
        self.showNormal()
        if self._normal_geo is not None:
            self.setGeometry(self._normal_geo)

    def toggle_max(self):
        if self.isMaximized() or self.isFullScreen():
            self._go_normal()
        else:
            self._remember_normal()
            self.showMaximized()

    def toggle_full(self):
        if self.isFullScreen():
            self._go_normal()
        else:
            self._remember_normal()
            self.showFullScreen()

    def next_theme(self):
        names = [th.name for th in THEMES]
        cur = names.index(self.t.name) if self.t.name in names else 0
        self.cfg["theme"] = names[(cur + 1) % len(names)]
        config.save(self.cfg)
        self.build_ui()

    def closeEvent(self, e):
        self._remember_normal()
        g = self._normal_geo or self.geometry()
        self.cfg["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        config.save(self.cfg)
        for f in self.feeds.values():
            f.stop()
        self._stop_tab_threads()
        self.hub.pool.clear()
        super().closeEvent(e)

    def _stop_tab_threads(self):
        for tab in self.tabs:
            if hasattr(tab, "beacons"):
                tab.beacons.stop()

    # ---- feeds -------------------------------------------------------------------------------
    def start_feeds(self):
        for f in self.feeds.values():
            f.stop()
        self.feeds = {}
        call = self.ctx.call
        if not call:
            return
        host, _, port = self.cfg.get("cluster", "dxc.ve7cc.net:23").partition(":")
        if host:
            self._add_feed("CLUSTER", TelnetFeed(host, int(port or 23), call, "CLUSTER"), self.ctx.add_spot)
        if self.cfg.get("rbn_cw", True):
            self._add_feed("RBN", TelnetFeed("telnet.reversebeacon.net", 7000, call, "RBN", filter_call=call),
                           self.ctx.add_rbn)
        if self.cfg.get("rbn_digi", True):
            self._add_feed("RBN-DIGI", TelnetFeed("telnet.reversebeacon.net", 7001, call, "RBN-DIGI",
                                                  filter_call=call), self.ctx.add_rbn)
        if self.cfg.get("aprs_on", True):
            lat, lon = self.ctx.qth
            feed = AprsFeed(call, lat, lon, int(self.cfg.get("aprs_km", 150)))
            feed.packet.connect(self.ctx.add_aprs)
            feed.state.connect(lambda msg, ok: self.ctx.feed_state.__setitem__("APRS", (msg, ok)))
            self.feeds["APRS"] = feed
            feed.start()

    def _add_feed(self, name, feed, sink):
        feed.spot.connect(sink)
        feed.state.connect(lambda msg, ok, n=name: self.ctx.feed_state.__setitem__(n, (msg, ok)))
        self.feeds[name] = feed
        feed.start()

    # ---- data dispatch --------------------------------------------------------------------------
    def _on_data(self, key, data):
        for tab in self.tabs:
            if key in tab.keys:
                try:
                    tab.on_data(key, data)
                except Exception:        # noqa: BLE001 - one bad payload must not take the page down
                    import traceback
                    traceback.print_exc()

    def _tick(self):
        now = time.time()
        self.clock.setText(time.strftime("%H:%M:%S", time.gmtime(now)) + "z")
        srcs = list(self.hub.sources.values())
        ok = sum(1 for s in srcs if s.last_ok and not s.error)
        err = [s for s in srcs if s.error]
        feeds_ok = sum(1 for f in self.feeds.values() if f.connected)
        col = self.t.main if not err else self.t.amber if len(err) <= 3 else self.t.red
        self.net_led.set_state(f"DATA {ok}/{len(srcs)} · LIVE {feeds_ok}/{len(self.feeds)}", col, True)
        for tab in self.tabs:
            if hasattr(tab, "background_tick"):
                try:
                    tab.background_tick()
                except Exception:       # noqa: BLE001
                    import traceback
                    traceback.print_exc()
        if 0 <= self.cur < len(self.tabs):
            try:
                self.tabs[self.cur].tick()
            except Exception:           # noqa: BLE001
                import traceback
                traceback.print_exc()
        if self._sources_dlg and self._sources_dlg.isVisible():
            self._sources_dlg.refresh()

    # ---- dialogs ---------------------------------------------------------------------------------
    def show_sources(self):
        if self._sources_dlg is None:
            self._sources_dlg = SourcesDialog(self)
        self._sources_dlg.refresh()
        self._sources_dlg.show()
        self._sources_dlg.raise_()

    def show_setup(self):
        dlg = SetupDialog(self)
        if dlg.exec():
            old = (self.cfg.get("callsign"), self.cfg.get("grid"), self.cfg.get("cluster"),
                   self.cfg.get("rbn_cw"), self.cfg.get("rbn_digi"), self.cfg.get("zoom"))
            old2 = {k: self.cfg.get(k) for k in ("show_myshack", "licence", "bom_state", "bom_radar", "aprs_on",
                                                 "aprs_km", "aprs_tiles")}
            self.cfg.update(dlg.values())
            config.save(self.cfg)
            if old[5] != self.cfg.get("zoom") or old2["show_myshack"] != self.cfg["show_myshack"] or \
                    old2["licence"] != self.cfg["licence"] or \
                    old2["aprs_tiles"] != self.cfg.get("aprs_tiles", True):
                cur_cls = type(self.tabs[self.cur]) if 0 <= self.cur < len(self.tabs) else None
                self.build_ui()
                self.show_tab(next((i for i, tab in enumerate(self.tabs) if type(tab) is cur_cls), 0))
            aprs_moved = (old[1], old2["aprs_km"]) != (self.cfg["grid"], self.cfg["aprs_km"])
            if (old[0], old[2], old[3], old[4], old2["aprs_on"]) != (
                    self.cfg["callsign"], self.cfg["cluster"], self.cfg["rbn_cw"], self.cfg["rbn_digi"],
                    self.cfg["aprs_on"]) or aprs_moved:
                self.ctx.rbn_me.clear()
                if aprs_moved:
                    self.ctx.aprs.clear()
                    self.ctx.aprs_log.clear()
                    for tab in self.tabs:
                        if isinstance(tab, AprsTab):
                            tab.qth_changed()
                self.start_feeds()
            if old2["bom_state"] != self.cfg["bom_state"]:
                self.hub.refresh("bom_warn")
            if old2["bom_radar"] != self.cfg["bom_radar"]:
                self.hub.refresh("radar")
            if old[1] != self.cfg["grid"] or old[0] != self.cfg["callsign"]:
                for tab in self.tabs:
                    tab.qth_changed()
                for k in ("weather", "wspr", "psk_me", "psk_grid"):
                    self.hub.refresh(k)
            if "tle" in self.hub.data:
                for tab in self.tabs:
                    if isinstance(tab, SatTab):
                        tab.on_data("tle", self.hub.data["tle"])
            self._update_station()
            self.tabs[self.cur].tick()


class SourcesDialog(QDialog):
    def __init__(self, win: DashWindow):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Data sources")
        self.resize(px(1180), px(720))
        t = win.t
        lay = QVBoxLayout(self)
        self.tb = make_table(["SOURCE", "STATUS", "UPDATED", "EVERY", "SIZE", "CREDIT / DETAIL"],
                             {0: 250, 1: 70, 2: 80, 3: 64, 4: 70}, stretch_col=5)
        self.feeds = make_table(["LIVE FEED", "STATE", "LINES"], {0: 250, 1: 520}, stretch_col=2)
        self.feeds.setMaximumHeight(px(120))
        self.later = make_table(["NOT YET INCLUDED", "WHY", "TAB"], {0: 380, 1: 560}, stretch_col=2)
        self.later.setMaximumHeight(px(190))
        fill_table(self.later, DEFERRED)
        lay.addWidget(panel(t, "INTERNET SOURCES (free, no key)", [self.tb, note(
            "All free sources are polled at their stated interval. Failures retry every 2 minutes. The last good "
            "copy of each is cached, so the dashboard starts with it (marked 'cached') when the PC is offline.")],
                            dot=t.main))
        lay.addWidget(panel(t, "STREAMING FEEDS", self.feeds, dot=t.sub))
        lay.addWidget(panel(t, "LATER (keys, accounts or unsolved)", self.later, dot=t.amber))
        close = QPushButton("CLOSE")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def refresh(self):
        t = self.win.t
        rows, colors = [], []
        for s in self.win.hub.sources.values():
            if s.enabled and not s.enabled():
                st, col = "needs SETUP", t.dim
            elif s.busy:
                st, col = "fetching", t.sub
            elif s.error:
                st, col = "ERROR", t.red
            elif s.stale:
                st, col = "cached", t.amber
            elif s.last_ok:
                st, col = "OK", t.main
            else:
                st, col = "waiting", t.dim
            every = f"{s.interval // 3600}h" if s.interval >= 3600 else f"{s.interval // 60}m"
            size = f"{s.size / 1024:.0f} kB" if s.size else ""
            rows.append((s.name, st, ago(s.last_ok) + (" ago" if s.last_ok else ""), every, size,
                         s.error or s.attribution))
            colors.append(col if st != "OK" else None)
        fill_table(self.tb, rows, colors)
        frows = [(n, f"{f.host}:{f.port} · " + self.win.ctx.feed_state.get(n, ("", False))[0], f.lines)
                 for n, f in self.win.feeds.items()]
        fill_table(self.feeds, frows, [t.main if f.connected else t.amber for f in self.win.feeds.values()],
                   right={2})


class SetupDialog(QDialog):
    def __init__(self, win: DashWindow):
        super().__init__(win)
        self.setWindowTitle("Setup")
        cfg = win.cfg
        t = win.t
        self.call = QLineEdit(cfg.get("callsign", ""))
        self.call.setPlaceholderText("your callsign (needed for the cluster, RBN, PSKReporter and APRS)")
        self.grid = QLineEdit(cfg.get("grid", ""))
        self.grid.setPlaceholderText("6-character locator, e.g. QF22lb")
        self.grid_note = note("")
        self.grid.textChanged.connect(self._check_grid)
        self.cluster = QLineEdit(cfg.get("cluster", ""))
        self.rbn_cw = QCheckBox("Reverse Beacon Network: CW / RTTY skimmers (port 7000)")
        self.rbn_cw.setChecked(cfg.get("rbn_cw", True))
        self.rbn_digi = QCheckBox("Reverse Beacon Network: FT8 / FT4 skimmers (port 7001)")
        self.rbn_digi.setChecked(cfg.get("rbn_digi", True))
        self.wind = QSpinBox()
        self.wind.setRange(10, 200)
        self.wind.setSuffix(" km/h")
        self.wind.setValue(int(cfg.get("wind_alert_kmh", 60)))
        self.min_el = QSpinBox()
        self.min_el.setRange(0, 60)
        self.min_el.setSuffix("°")
        self.min_el.setValue(int(cfg.get("sat_min_el", 10)))
        self.licence = QComboBox()
        self.licence.addItems(list(LEVELS))
        self.licence.setCurrentText(cfg.get("licence", "Advanced"))
        self.bom_state = QComboBox()
        self.bom_state.addItems(list(BOM_STATES))
        self.bom_state.setCurrentText(cfg.get("bom_state", "VIC"))
        self.bom_radar = QLineEdit(cfg.get("bom_radar", "IDR023"))
        self.bom_radar.setPlaceholderText("e.g. IDR023 Melbourne 128 km, IDR022 Melbourne 256 km")
        self.aprs_on = QCheckBox("APRS-IS feed for the L tab (receive only, nothing is transmitted)")
        self.aprs_on.setChecked(cfg.get("aprs_on", True))
        self.aprs_km = QSpinBox()
        self.aprs_km.setRange(10, 1000)
        self.aprs_km.setSuffix(" km")
        self.aprs_km.setValue(int(cfg.get("aprs_km", 150)))
        self.aprs_tiles = QCheckBox("Detailed APRS map background (downloads OpenStreetMap tiles, shown dark)")
        self.aprs_tiles.setChecked(cfg.get("aprs_tiles", True))
        self.updates = QCheckBox("Check GitHub for a newer ShackDash when the program starts")
        self.updates.setChecked(cfg.get("check_updates", True))
        self.myshack = QCheckBox("Show the MY SHACK tab (my own hotspots, switches and LAN gear)")
        self.myshack.setChecked(cfg.get("show_myshack", True))
        self.zoom = QComboBox()
        for z in (0.8, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.zoom.addItem(f"× {z:g}", z)
        self.zoom.setCurrentIndex(max(0, self.zoom.findData(float(cfg.get("zoom", 1.0)))))
        form = QFormLayout()
        form.addRow("Callsign", self.call)
        form.addRow("Grid locator (QTH)", self.grid)
        form.addRow("", self.grid_note)
        form.addRow("DX cluster host:port", self.cluster)
        form.addRow("", self.rbn_cw)
        form.addRow("", self.rbn_digi)
        form.addRow("Antenna wind alert at", self.wind)
        form.addRow("Satellite passes above", self.min_el)
        form.addRow("Text / panel size", self.zoom)
        form2 = QFormLayout()
        form2.addRow("Licence level (Australia)", self.licence)
        form2.addRow("BoM warnings for", self.bom_state)
        form2.addRow("BoM radar ID", self.bom_radar)
        form2.addRow("", self.aprs_on)
        form2.addRow("APRS radius", self.aprs_km)
        form2.addRow("", self.aprs_tiles)
        form2.addRow("", self.myshack)
        form2.addRow("", self.updates)
        lay = QVBoxLayout(self)
        if not cfg.get("qth_confirmed"):
            welcome = note("Welcome to ShackDash. Enter your callsign and grid locator: distances, beam headings, "
                           "weather and satellite passes are all worked out from them. Nothing that uses your "
                           "callsign connects until it is set.")
            welcome.setWordWrap(True)
            lay.addWidget(welcome)
        lay.addWidget(panel(t, "STATION", form, dot=t.main))
        lay.addWidget(panel(t, "MORE", form2, dot=t.sub))
        btns = QHBoxLayout()
        btns.addStretch(1)
        for text, fn in (("CANCEL", self.reject), ("SAVE", self._save)):
            b = QPushButton(text)
            b.setMinimumWidth(px(110))
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        self._check_grid(self.grid.text())

    def _check_grid(self, g):
        ll = grid_to_latlon(g.strip())
        self.grid_note.setText(f"= {ll[0]:.3f}, {ll[1]:.3f}" if ll else
                               "not a valid locator" if g.strip() else "needed: your Maidenhead locator")

    def _save(self):
        if not grid_to_latlon(self.grid.text().strip()):
            self.grid_note.setText("not a valid locator. Use e.g. QF22lb")
            return
        self.accept()

    def values(self) -> dict:
        return {"callsign": self.call.text().strip().upper(), "grid": self.grid.text().strip()[:2].upper()
                + self.grid.text().strip()[2:4] + self.grid.text().strip()[4:6].lower() + self.grid.text().strip()[6:],
                "qth_confirmed": True, "cluster": self.cluster.text().strip(), "rbn_cw": self.rbn_cw.isChecked(),
                "rbn_digi": self.rbn_digi.isChecked(), "wind_alert_kmh": self.wind.value(),
                "sat_min_el": self.min_el.value(), "zoom": self.zoom.currentData(),
                "licence": self.licence.currentText(), "bom_state": self.bom_state.currentText(),
                "bom_radar": self.bom_radar.text().strip().upper() or "IDR023", "aprs_on": self.aprs_on.isChecked(),
                "aprs_km": self.aprs_km.value(), "aprs_tiles": self.aprs_tiles.isChecked(), "show_myshack": self.myshack.isChecked(),
                "check_updates": self.updates.isChecked()}
