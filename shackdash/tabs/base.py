"""Shared context and the tab base class."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLayout, QLineEdit, QVBoxLayout, QWidget

from ..geo import grid_to_latlon
from ..theme import Theme, px
from ..widgets import DeckButton, Fieldset


class Ctx(QObject):
    """Everything the tabs share: settings, theme, the data hub, the telnet
    feeds' spot store and the prefix database."""
    spotsChanged = Signal()
    heardChanged = Signal()
    aprsChanged = Signal()

    def __init__(self, cfg: dict, hub):
        super().__init__()
        self.cfg = cfg
        self.hub = hub
        self.t: Theme | None = None
        self.spots: list[dict] = []          # DX cluster, newest first
        self.rbn_me: list[dict] = []         # RBN spots of my call, newest first
        self.feed_state: dict[str, tuple[str, bool]] = {}
        self.aprs: dict[str, dict] = {}      # station/object name -> latest state (+ track)
        self.aprs_log: list[dict] = []       # every packet, newest first
        self.shack_links: dict[str, str] = {}  # reflector (e.g. REF023) -> my hotspot linked to it (tab O)

    @property
    def call(self) -> str:
        return self.cfg.get("callsign", "").upper()

    @property
    def qth(self) -> tuple[float, float]:
        return grid_to_latlon(self.cfg.get("grid", "QF22")) or (-37.5, 145.0)

    @property
    def cty(self):
        return self.hub.data.get("cty")

    def add_spot(self, sp: dict):
        self.spots.insert(0, sp)
        del self.spots[1500:]
        self.spotsChanged.emit()

    def add_aprs(self, p: dict):
        self.aprs_log.insert(0, p)
        del self.aprs_log[600:]
        name = p.get("obj") or p["src"]
        if "lat" in p or p["kind"] in ("weather", "status"):
            st = self.aprs.setdefault(name, {"name": name, "first": p["t"], "n": 0, "track": [], "kind": p["kind"]})
            st["n"] += 1
            st["t"] = p["t"]
            st["via"] = p["src"]
            for k in ("lat", "lon", "table", "sym", "what", "course", "speed_kt", "alt_ft", "temp_c", "wind_kmh",
                      "alive"):
                if k in p:
                    st[k] = p[k]
            if p.get("comment"):
                st["comment"] = p["comment"]
            if p["kind"] in ("position", "object", "weather"):
                st["kind"] = p["kind"]
            if "lat" in p:
                tr = st["track"]
                if not tr or (abs(tr[-1][1] - p["lat"]) + abs(tr[-1][2] - p["lon"]) > 1e-4):
                    tr.append((p["t"], p["lat"], p["lon"]))
                    del tr[:-30]
        cutoff = p["t"] - 6 * 3600
        if len(self.aprs) > 800:
            for k in [k for k, v in self.aprs.items() if v["t"] < cutoff]:
                del self.aprs[k]
        self.aprsChanged.emit()

    def add_rbn(self, sp: dict):
        self.rbn_me.insert(0, sp)
        cutoff = time.time() - 6 * 3600
        self.rbn_me = [s for s in self.rbn_me if s["t"] > cutoff][:500]
        self.heardChanged.emit()


class Tab(QWidget):
    """A dashboard page. Subclasses build their panels in build() and react
    to hub updates in on_data(); tick() runs once a second while visible."""
    keys: tuple[str, ...] = ()               # hub sources this tab listens to
    title = ""
    footer = ""                              # attribution line shown under the page

    def __init__(self, ctx: Ctx):
        super().__init__()
        self.ctx = ctx
        self.t = ctx.t
        self.build()
        for k in self.keys:
            if k in ctx.hub.data:
                try:
                    self.on_data(k, ctx.hub.data[k])
                except Exception:           # noqa: BLE001 - a bad cached payload must not stop start-up
                    import traceback
                    traceback.print_exc()

    def build(self):
        pass

    def on_data(self, key: str, data):
        pass

    def tick(self):
        pass

    def qth_changed(self):
        pass


def panel(t: Theme, title: str, content, dot: str | None = None, pad: int = 10) -> Fieldset:
    fs = Fieldset(t, title, dot=dot or t.sub)
    lay = QVBoxLayout(fs)
    lay.setContentsMargins(*fs.margins(pad))
    lay.setSpacing(px(6))
    if isinstance(content, QLayout):
        lay.addLayout(content)
    elif isinstance(content, (list, tuple)):
        for c in content:
            if isinstance(c, QLayout):
                lay.addLayout(c)
            else:
                lay.addWidget(c, getattr(c, "_stretch", 1 if not isinstance(c, (QLabel, QLineEdit)) else 0))
    else:
        lay.addWidget(content)
    return fs


def stretch(w: QWidget, n: int) -> QWidget:
    w._stretch = n
    return w


def note(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("note")
    lb.setWordWrap(True)
    return lb


def key_row(t: Theme, names: list[str], on_pick, current: str | None = None, height: int = 30):
    """A row of 3D keys acting as a radio group (filters)."""
    row = QHBoxLayout()
    row.setSpacing(px(6))
    keys = {}

    def pick(n):
        for k, b in keys.items():
            b.set_state(active=(k == n))
        on_pick(n)
    for n in names:
        b = DeckButton(t, n, led=True)
        b.setMinimumHeight(px(height))
        b.setMaximumHeight(px(height + 4))
        b.set_state(active=(n == (current or names[0])))
        b.clicked.connect(lambda n=n: pick(n))
        keys[n] = b
        row.addWidget(b)
    row._keys = keys
    return row


def ago(ts: float | None) -> str:
    if not ts:
        return ""
    d = time.time() - ts
    if d < 0:
        return "future"
    if d < 90:
        return f"{int(d)}s"
    if d < 5400:
        return f"{int(d / 60)}m"
    if d < 172800:
        return f"{d / 3600:.1f}h"
    return f"{int(d / 86400)}d"


def hhmm_utc(ts: float) -> str:
    return time.strftime("%H:%M", time.gmtime(ts))


def local_str(ts: float, fmt: str = "%a %H:%M") -> str:
    return time.strftime(fmt, time.localtime(ts))


def hline_search(placeholder: str, on_text) -> QLineEdit:
    e = QLineEdit()
    e.setPlaceholderText(placeholder)
    e.setClearButtonEnabled(True)
    e.textChanged.connect(on_text)
    return e


ALIGN_R = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
