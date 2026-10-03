"""G · VHF/UHF PROPAGATION: Hepburn tropo forecast, VHF+ spots, Es/aurora outlook"""
from __future__ import annotations

import re
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSlider, QWidget

from ..geo import bearing_distance, gc_points, grid_to_latlon
from ..instruments import fill_table, make_table
from ..mapview import MapView
from ..theme import px
from ..widgets import DeckButton, font, paint_recess, qc
from .base import Tab, key_row, note, panel, stretch

GRID_RE = re.compile(r"\b([A-R]{2}\d{2}(?:[A-X]{2})?)\b", re.I)
TROPO_BASE = "https://www.dxinfocentre.com/tr_map/fcst/"


class ImageScreen(QWidget):
    def __init__(self, t):
        super().__init__()
        self.t = t
        self.img: QImage | None = None
        self.msg = "loading forecast…"
        self.caption = ""
        self.setMinimumSize(px(300), px(260))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_image(self, img, msg=""):
        self.img, self.msg = img, msg
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_recess(p, r, self.t, px(10))
        inner = r.adjusted(px(8), px(8), -px(8), -px(8))
        if self.img is None or self.img.isNull():
            p.setPen(qc(self.t.faint))
            p.setFont(font(px(13)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.msg)
            return
        s = min(inner.width() / self.img.width(), inner.height() / self.img.height())
        w, h = self.img.width() * s, self.img.height() * s
        p.drawImage(QRectF(inner.center().x() - w / 2, inner.center().y() - h / 2, w, h), self.img)
        if self.caption:
            p.setFont(font(px(11.5), bold=True))
            box = QRectF(r.left() + px(8), r.bottom() - px(26), r.width() - px(16), px(20))
            p.setPen(qc("#000000", 200))
            p.drawText(box.translated(1, 1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)
            p.setPen(qc(self.t.text))
            p.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.caption)


class VhfTab(Tab):
    title = "G · VHF/UHF"
    keys = ("tropo_idx", "hamqsl", "land", "cty")
    footer = ("Tropo ducting forecast © William Hepburn, dxinfocentre.com (images, personal use) · VHF spots from "
              "the DX cluster · VHF Es/aurora outlook from N0NBH")

    def build(self):
        t = self.t
        self.frames: list[str] = []
        self.cache: dict[str, QImage] = {}
        self.band = "ALL VHF+"
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        g.setVerticalSpacing(px(8))
        self.screen = ImageScreen(t)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._show)
        self.frame_lbl = QLabel("")
        self.frame_lbl.setMinimumWidth(px(250))
        self.play = DeckButton(t, "PLAY", led=True)
        self.play.setFixedSize(px(92), px(34))
        self.play.clicked.connect(self._toggle_play)
        ctl = QHBoxLayout()
        ctl.addWidget(self.play)
        ctl.addWidget(self.slider, 1)
        ctl.addWidget(self.frame_lbl)
        g.addWidget(panel(t, "TROPOSPHERIC DUCTING FORECAST  ·  AUSTRALIA (HEPBURN)",
                          [self.screen, ctl, note("Colours show the forecast ducting index. Warmer colours mean "
                                                  "better VHF/UHF tropo paths. The slider shows each frame's valid "
                                                  "time and opens on the one nearest now.")], dot=t.amber), 0, 0, 2, 1)
        self.vhf_cond = note("")
        self.spots = make_table(["UTC", "MHz", "DX", "SPOTTER", "km", "COMMENT"], {0: 48, 1: 78, 2: 90, 3: 90, 4: 56},
                                stretch_col=5)
        g.addWidget(panel(t, "VHF / UHF SPOTS  ·  DX CLUSTER",
                          [key_row(t, ["ALL VHF+", "6m", "4m", "2m", "70cm"], self._pick, height=30), self.vhf_cond,
                           self.spots], dot=t.main), 0, 1)
        self.map = MapView(t, center_lon=self.ctx.qth[1])
        g.addWidget(panel(t, "VHF+ PATHS (from locators in the spots)", self.map, dot=t.sub), 1, 1)
        g.setColumnStretch(0, 48)
        g.setColumnStretch(1, 52)
        g.setRowStretch(0, 1)
        g.setRowStretch(1, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        self.ctx.spotsChanged.connect(self._spots_dirty)
        self._dirty = True
        self._draw_spots()

    # ---- tropo images -----------------------------------------------------------------
    def on_data(self, key, d):
        if key == "tropo_idx":
            first = not self.frames
            self.frames = d
            self.slider.setRange(0, max(0, len(d) - 1))
            if first:                                    # open on the frame nearest to now
                now = time.time()
                best = min(range(len(d)), key=lambda i: abs((d[i][1] or 0) - now)) if d else 0
                self.slider.setValue(best)
            self._show(self.slider.value())
        elif key == "hamqsl":
            items = [f"{n.replace('vhf-aurora', 'Aurora').replace('E-Skip', 'Es')} "
                     f"{loc.replace('_', ' ')}: {s}" for n, loc, s in d.get("vhf", [])]
            self.vhf_cond.setText("N0NBH VHF outlook: " + " · ".join(items) + f" · aurora lat {d.get('latdegree', '')}°")
        elif key == "land":
            self.map.set_land(d)
        elif key == "cty":
            self._dirty = True
            self._draw_spots()

    def _show(self, i):
        if not self.frames:
            return
        name, valid, url = self.frames[min(i, len(self.frames) - 1)]
        if valid:
            self.frame_lbl.setText(time.strftime("%a %H%Mz", time.gmtime(valid)) +
                                   time.strftime("  (%a %H:%M local)", time.localtime(valid)))
        else:
            self.frame_lbl.setText(f"frame +{int(name[3:]):03d} h")
        if name in self.cache:
            self.screen.set_image(self.cache[name])
            return
        self.screen.set_image(self.screen.img, "loading…")

        def got(data, err, name=name):
            if err or not data:
                self.screen.set_image(None, f"could not load {name}: {err}")
                return
            img = QImage.fromData(data)
            self.cache[name] = img
            if self.frames and self.frames[min(self.slider.value(), len(self.frames) - 1)][0] == name:
                self.screen.set_image(img)
        self.ctx.hub.fetch_once(url, lambda raw: raw, got)

    def _toggle_play(self):
        on = not self.timer.isActive()
        self.play.set_state(active=on, text="STOP" if on else "PLAY")
        if on:
            self.timer.start(900)
        else:
            self.timer.stop()

    def _step(self):
        if self.frames:
            self.slider.setValue((self.slider.value() + 1) % len(self.frames))

    # ---- VHF spots ------------------------------------------------------------------------------
    def _pick(self, b):
        self.band = b
        self._dirty = True
        self._draw_spots()

    def _spots_dirty(self):
        self._dirty = True

    def _draw_spots(self):
        if not self._dirty:
            return
        self._dirty = False
        t = self.t
        cty = self.ctx.cty
        lat, lon = self.ctx.qth
        rows, colors, paths, markers = [], [], [], []
        for sp in self.ctx.spots:
            if sp["khz"] < 50000:
                continue
            if self.band != "ALL VHF+" and sp["band"] != self.band:
                continue
            grids = GRID_RE.findall(sp["comment"])
            a = z = None
            if len(grids) >= 2:
                a, z = grid_to_latlon(grids[0]), grid_to_latlon(grids[1])
            if not (a and z) and cty:
                e1, e2 = cty.lookup(sp["spotter"]), cty.lookup(sp["dx"])
                a = a or (e1 and (e1.lat, e1.lon))
                z = z or (e2 and (e2.lat, e2.lon))
            km = f"{bearing_distance(*a, *z)[1]:.0f}" if a and z else ""
            rows.append((sp["time"], f"{sp['khz'] / 1000:.3f}", sp["dx"], sp["spotter"], km, sp["comment"]))
            col = t.purple if sp["band"] == "6m" else t.main if sp["band"] == "2m" else t.amber
            colors.append(col)
            if a and z and len(paths) < 150 and time.time() - sp["t"] < 3 * 3600:
                paths.append((gc_points(*a, *z, 40), col, 1.0, False))
                markers.append((z[0], z[1], col, "", 7))
        markers.append((lat, lon, t.sub, self.ctx.call or "QTH", 12))
        fill_table(self.spots, rows[:300], colors[:300], right={1, 4})
        self.map.set_overlays(markers=markers, paths=paths,
                              caption="purple 6m · amber 4m/70cm · green 2m · last 3 h (spots since the app started)")

    def qth_changed(self):
        self.map.set_center(self.ctx.qth[1])

    def tick(self):
        self._draw_spots()
