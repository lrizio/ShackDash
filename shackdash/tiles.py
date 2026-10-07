"""Web-map tiles (standard OpenStreetMap tiles, recoloured dark here) for the APRS map background.
Tiles are fetched on a small background pool, kept in memory and cached on disk so a
repeat view costs nothing and works offline. Only the tile coordinates are sent."""
from __future__ import annotations

import math
import os
import time
from collections import OrderedDict

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
import numpy as np
from PySide6.QtGui import QImage, QPixmap

from . import config
from .net import http_get

URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = "© OpenStreetMap contributors"
CACHE_DIR = os.path.join(config.APP_DIR, "tiles")
MAX_AGE = 30 * 86400
RETRY_S = 90
MAX_Z = 17


def tile_x(lon: float, z: int) -> float:
    return (lon + 180.0) / 360.0 * (1 << z)


def tile_y(lat: float, z: int) -> float:
    lat = max(-85.05, min(85.05, lat))
    r = math.radians(lat)
    return (1 - math.asinh(math.tan(r)) / math.pi) / 2 * (1 << z)


def tile_lon(x: float, z: int) -> float:
    return x / (1 << z) * 360.0 - 180.0


def tile_lat(y: float, z: int) -> float:
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / (1 << z)))))


# CSS "invert(1) hue-rotate(180deg)": turns the light OSM style dark while keeping water blue / parks green
_HUE = np.array([[-0.574, 1.430, 0.144], [0.426, 0.430, 0.144], [0.426, 1.430, -0.856]], dtype=np.float32)


def darken(data: bytes) -> QImage | None:
    img = QImage.fromData(data)
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), dtype=np.uint8).reshape(h, img.bytesPerLine())[:, :w * 3]
    rgb = 255.0 - a.reshape(h, w, 3).astype(np.float32)
    out = np.clip((rgb @ _HUE.T) * 0.9, 0, 255).astype(np.uint8)
    return QImage(out.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()


class _Job(QRunnable):
    def __init__(self, layer: "TileLayer", z: int, x: int, y: int):
        super().__init__()
        self.layer, self.key = layer, (z, x, y)

    def run(self):
        z, x, y = self.key
        path = os.path.join(CACHE_DIR, str(z), str(x), f"{y}.png")
        data = None
        try:
            if os.path.exists(path) and time.time() - os.path.getmtime(path) < MAX_AGE:
                with open(path, "rb") as f:
                    data = f.read()
            else:
                url = URL.format(z=z, x=x, y=y)
                data = http_get(url, {"Accept": "image/png"}, timeout=15)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
        except Exception:                       # noqa: BLE001 - offline / server hiccup: use a stale copy if any
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                data = None
        try:
            self.layer._done.emit(z, x, y, darken(data) if data else None)
        except RuntimeError:                    # window closed meanwhile
            pass


class TileLayer(QObject):
    changed = Signal()
    _done = Signal(int, int, int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mem: OrderedDict = OrderedDict()   # (z,x,y) -> QPixmap
        self._pending: set = set()
        self._failed: dict = {}
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.changed.emit)
        self._done.connect(self._arrived)

    def get(self, z: int, x: int, y: int) -> QPixmap | None:
        key = (z, x, y)
        pm = self._mem.get(key)
        if pm is not None:
            self._mem.move_to_end(key)
            return pm
        if key not in self._pending and time.time() - self._failed.get(key, 0) > RETRY_S:
            self._pending.add(key)
            self._pool.start(_Job(self, *key))
        return None

    def _arrived(self, z, x, y, data):
        key = (z, x, y)
        self._pending.discard(key)
        if data is not None:
            self._mem[key] = QPixmap.fromImage(data)
            while len(self._mem) > 300:
                self._mem.popitem(last=False)
        else:
            self._failed[key] = time.time()
        if not self._timer.isActive():
            self._timer.start()
