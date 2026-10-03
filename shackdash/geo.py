"""Maidenhead grids, great-circle maths and the callsign -> DXCC entity
lookup (AD1C country files, cty.csv)."""
from __future__ import annotations

import io
import math
import re
import zipfile

EARTH_KM = 6371.0


def grid_to_latlon(grid: str) -> tuple[float, float] | None:
    """Centre of a 4, 6 or 8 character Maidenhead locator."""
    g = grid.strip().upper()
    if not re.fullmatch(r"[A-R]{2}(\d\d([A-X]{2}(\d\d)?)?)?", g):
        return None
    lon = (ord(g[0]) - 65) * 20 - 180
    lat = (ord(g[1]) - 65) * 10 - 90
    w, h = 20.0, 10.0
    if len(g) >= 4:
        lon += int(g[2]) * 2
        lat += int(g[3])
        w, h = 2.0, 1.0
    if len(g) >= 6:
        lon += (ord(g[4]) - 65) * (5 / 60)
        lat += (ord(g[5]) - 65) * (2.5 / 60)
        w, h = 5 / 60, 2.5 / 60
    if len(g) >= 8:
        lon += int(g[6]) * (0.5 / 60)
        lat += int(g[7]) * (0.25 / 60)
        w, h = 0.5 / 60, 0.25 / 60
    return lat + h / 2, lon + w / 2


def latlon_to_grid(lat: float, lon: float, n: int = 6) -> str:
    lon = (lon + 180) % 360
    lat = max(0.0, min(179.9999, lat + 90))
    g = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    g += str(int(lon % 20 // 2)) + str(int(lat % 10))
    if n >= 6:
        g += chr(97 + int(lon % 2 * 12)) + chr(97 + int(lat % 1 * 24))
    return g


def bearing_distance(lat1, lon1, lat2, lon2) -> tuple[float, float]:
    """Initial short-path bearing (deg) and distance (km)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return brg, 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def gc_points(lat1, lon1, lat2, lon2, n: int = 90, long_path: bool = False) -> list[tuple[float, float]]:
    """Points along the great circle (short path, or the long way round)."""
    def vec(lat, lon):
        la, lo = math.radians(lat), math.radians(lon)
        return (math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la))
    a, b = vec(lat1, lon1), vec(lat2, lon2)
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    om = math.acos(dot)
    if om < 1e-9:
        return [(lat1, lon1)]
    # unit vector perpendicular to a, in the a-b plane, pointing toward b
    c = [bb - dot * aa for aa, bb in zip(a, b)]
    cn = math.sqrt(sum(x * x for x in c))
    c = [x / cn for x in c]
    total = (2 * math.pi - om) if long_path else om
    sign = -1 if long_path else 1
    pts = []
    for i in range(n + 1):
        th = sign * total * i / n
        v = [math.cos(th) * aa + math.sin(th) * cc for aa, cc in zip(a, c)]
        pts.append((math.degrees(math.asin(max(-1, min(1, v[2])))), math.degrees(math.atan2(v[1], v[0]))))
    return pts


def compass(brg: float) -> str:
    return ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][
        int((brg + 11.25) % 360 // 22.5)]


# ---- DXCC lookup ------------------------------------------------------------------

class Entity(tuple):
    """(name, adif, continent, cq, itu, lat, lon, utc_offset)"""
    __slots__ = ()
    name = property(lambda s: s[0])
    adif = property(lambda s: s[1])
    cont = property(lambda s: s[2])
    lat = property(lambda s: s[5])
    lon = property(lambda s: s[6])


class Cty:
    """Longest-prefix callsign lookup from cty.csv (AD1C, country-files.com)."""

    def __init__(self):
        self.prefix: dict[str, Entity] = {}
        self.exact: dict[str, Entity] = {}
        self.by_adif: dict[int, Entity] = {}
        self.main_prefix: dict[int, str] = {}
        self.maxlen = 1

    @classmethod
    def from_zip(cls, raw: bytes) -> "Cty":
        z = zipfile.ZipFile(io.BytesIO(raw))
        return cls.from_csv(z.read("cty.csv").decode("latin-1"))

    @classmethod
    def from_csv(cls, text: str) -> "Cty":
        c = cls()
        for line in text.splitlines():
            parts = line.split(",")
            if len(parts) < 10:
                continue
            try:
                # cty.csv longitudes are positive WEST; flip to the usual east-positive
                ent = Entity((parts[1], int(parts[2]), parts[3], int(parts[4]), int(parts[5]),
                              float(parts[6]), -float(parts[7]), float(parts[8])))
            except ValueError:
                continue
            main = parts[0].lstrip("*")
            c.by_adif.setdefault(ent.adif, ent)
            c.main_prefix.setdefault(ent.adif, main)
            for alias in parts[9].rstrip(";").split():
                exact = alias.startswith("=")
                a = re.sub(r"[\(\[<{~].*$", "", alias.lstrip("="))
                if not a:
                    continue
                (c.exact if exact else c.prefix)[a] = ent
                if not exact:
                    c.maxlen = max(c.maxlen, len(a))
            c.prefix.setdefault(main, ent)
        return c

    def lookup(self, call: str) -> Entity | None:
        call = call.upper().strip()
        if not call:
            return None
        if call in self.exact:
            return self.exact[call]
        base = re.sub(r"/(P|M|MM|AM|QRP|A|B|R|LH|\d)$", "", call)
        if base in self.exact:
            return self.exact[base]
        if "/" in base:
            a, b = base.split("/", 1)
            # VK9/K1ABC or K1ABC/VK9: the shorter part is the operating prefix
            base = a if len(a) <= len(b) else b
        for n in range(min(len(base), self.maxlen), 0, -1):
            ent = self.prefix.get(base[:n])
            if ent:
                return ent
        return None
