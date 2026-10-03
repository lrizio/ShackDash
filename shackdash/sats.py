"""Satellite passes, live look angles and Doppler from CelesTrak TLEs
(SGP4 via the sgp4 package; vectorised with numpy for the pass search)."""
from __future__ import annotations

import math
import time

import numpy as np
from sgp4.api import Satrec, SatrecArray, jday

C_KMS = 299_792.458
OMEGA_E = 7.2921150e-5          # rad/s
A_E, F_E = 6378.137, 1 / 298.257223563


def parse_tle(text: str) -> list[dict]:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    sats, i = [], 0
    while i + 2 < len(lines) + 1:
        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            try:
                rec = Satrec.twoline2rv(l1, l2)
                sats.append({"name": name, "norad": int(l1[2:7]), "rec": rec, "l1": l1, "l2": l2})
            except ValueError:
                pass
            i += 3
        else:
            i += 1
    return sats


def _gmst_rad(jd_ut1: np.ndarray) -> np.ndarray:
    t = (jd_ut1 - 2451545.0) / 36525.0
    g = 67310.54841 + (876600.0 * 3600 + 8640184.812866) * t + 0.093104 * t * t - 6.2e-6 * t ** 3
    return np.mod(g % 86400.0 / 240.0 * math.pi / 180, 2 * math.pi)


def observer_ecef(lat: float, lon: float, alt_km: float = 0.0) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lon)
    e2 = F_E * (2 - F_E)
    n = A_E / math.sqrt(1 - e2 * math.sin(la) ** 2)
    return np.array([(n + alt_km) * math.cos(la) * math.cos(lo), (n + alt_km) * math.cos(la) * math.sin(lo),
                     (n * (1 - e2) + alt_km) * math.sin(la)])


def _teme_to_ecef(r, v, gmst):
    c, s = np.cos(gmst), np.sin(gmst)
    x = c * r[..., 0] + s * r[..., 1]
    y = -s * r[..., 0] + c * r[..., 1]
    re = np.stack([x, y, r[..., 2]], axis=-1)
    vx = c * v[..., 0] + s * v[..., 1] + OMEGA_E * y
    vy = -s * v[..., 0] + c * v[..., 1] - OMEGA_E * x
    ve = np.stack([vx, vy, v[..., 2]], axis=-1)
    return re, ve


def _look(re, ve, lat, lon, obs):
    la, lo = math.radians(lat), math.radians(lon)
    rho = re - obs
    sl, cl, so, co = math.sin(la), math.cos(la), math.sin(lo), math.cos(lo)
    south = sl * co * rho[..., 0] + sl * so * rho[..., 1] - cl * rho[..., 2]
    east = -so * rho[..., 0] + co * rho[..., 1]
    up = cl * co * rho[..., 0] + cl * so * rho[..., 1] + sl * rho[..., 2]
    rng = np.linalg.norm(rho, axis=-1)
    el = np.degrees(np.arcsin(np.clip(up / rng, -1, 1)))
    az = np.degrees(np.arctan2(east, -south)) % 360
    rate = np.sum(rho * ve, axis=-1) / rng
    return az, el, rng, rate


def _times(start: float, n: int, step: float):
    ts = start + np.arange(n) * step
    jd_full = ts / 86400.0 + 2440587.5
    jd_i = np.floor(jd_full)
    return ts, jd_i, jd_full - jd_i


def find_passes(sats: list[dict], lat: float, lon: float, min_el: float, start: float | None = None,
                hours: float = 24, step: float = 30.0) -> list[dict]:
    """All passes (AOS/TCA/LOS, max elevation) above min_el in the window."""
    start = start or time.time()
    n = int(hours * 3600 / step) + 1
    ts, jd_i, fr = _times(start, n, step)
    obs = observer_ecef(lat, lon)
    gm = _gmst_rad(jd_i + fr)
    out = []
    batch = 40
    for b in range(0, len(sats), batch):
        chunk = sats[b:b + batch]
        e, r, v = SatrecArray([s["rec"] for s in chunk]).sgp4(jd_i, fr)
        re, ve = _teme_to_ecef(r, v, gm)
        az, el, rng, _ = _look(re, ve, lat, lon, obs)
        for k, s in enumerate(chunk):
            elk = np.where(e[k] == 0, el[k], -90)
            up = elk > 0
            if not up.any():
                continue
            edges = np.diff(up.astype(int))
            starts = list(np.where(edges == 1)[0] + 1)
            ends = list(np.where(edges == -1)[0] + 1)
            if up[0]:
                starts.insert(0, 0)
            if up[-1]:
                ends.append(len(up))
            for a, z in zip(starts, ends):
                seg = elk[a:z]
                m = int(np.argmax(seg))
                if seg[m] < min_el:
                    continue
                out.append({"name": s["name"], "norad": s["norad"], "aos": float(ts[a]),
                            "los": float(ts[min(z, len(ts) - 1)]), "tca": float(ts[a + m]),
                            "max_el": float(seg[m]), "aos_az": float(az[k][a]),
                            "los_az": float(az[k][min(z, len(ts)) - 1]), "in_progress": a == 0 and up[0]})
    out.sort(key=lambda p: p["aos"])
    return out


def track(sat: dict, lat: float, lon: float, start: float, end: float, step: float = 20.0):
    """(ts, az, el) samples of one satellite over an interval (for the sky plot)."""
    n = max(2, int((end - start) / step) + 1)
    ts, jd_i, fr = _times(start, n, step)
    e, r, v = sat["rec"].sgp4_array(jd_i, fr)
    re, ve = _teme_to_ecef(r, v, _gmst_rad(jd_i + fr))
    az, el, _, _ = _look(re, ve, lat, lon, observer_ecef(lat, lon))
    return ts, az, el


def now_state(sat: dict, lat: float, lon: float, ts: float | None = None) -> dict | None:
    ts = ts or time.time()
    t, jd_i, fr = _times(ts, 1, 1)
    e, r, v = sat["rec"].sgp4_array(jd_i, fr)
    if e[0]:
        return None
    re, ve = _teme_to_ecef(r, v, _gmst_rad(jd_i + fr))
    az, el, rng, rate = _look(re, ve, lat, lon, observer_ecef(lat, lon))
    x, y, z = re[0]
    p = math.hypot(x, y)
    sub_lat = math.degrees(math.atan2(z, p * (1 - F_E * (2 - F_E))))
    sub_lon = math.degrees(math.atan2(y, x))
    alt = math.sqrt(x * x + y * y + z * z) - A_E
    return {"az": float(az[0]), "el": float(el[0]), "range": float(rng[0]), "rate": float(rate[0]),
            "lat": sub_lat, "lon": sub_lon, "alt": alt}


def ground_track(sat: dict, start: float, minutes: float = 100, step: float = 30) -> list[tuple[float, float]]:
    n = int(minutes * 60 / step) + 1
    ts, jd_i, fr = _times(start, n, step)
    e, r, v = sat["rec"].sgp4_array(jd_i, fr)
    re, _ = _teme_to_ecef(r, v, _gmst_rad(jd_i + fr))
    out = []
    for (x, y, z), err in zip(re, e):
        if err:
            continue
        out.append((math.degrees(math.atan2(z, math.hypot(x, y) * (1 - F_E * (2 - F_E)))),
                    math.degrees(math.atan2(y, x))))
    return out


def doppler_hz(freq_hz: float, range_rate_kms: float) -> float:
    """Received-frequency offset for a downlink (negative when receding)."""
    return -freq_hz * range_rate_kms / C_KMS
