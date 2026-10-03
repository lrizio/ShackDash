"""Low-precision sun and moon positions (good to a few arc-minutes for the
sun and ~0.3 deg for the moon; plenty for a dashboard), rise/set times,
sub-solar/sub-lunar points and the moon's distance for EME."""
from __future__ import annotations

import math
import time

D2R = math.pi / 180
MOON_PERIGEE_KM = 356_400.0


def jd(ts: float) -> float:
    return ts / 86400.0 + 2440587.5


def gmst_deg(j: float) -> float:
    return (280.46061837 + 360.98564736629 * (j - 2451545.0)) % 360


def _eq(lam_deg: float, beta_deg: float, j: float) -> tuple[float, float]:
    eps = (23.439 - 0.0000004 * (j - 2451545.0)) * D2R
    lam, beta = lam_deg * D2R, beta_deg * D2R
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    return (math.degrees(ra) % 360), math.degrees(dec)


def sun(ts: float) -> dict:
    j = jd(ts)
    n = j - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = ((357.528 + 0.9856003 * n) % 360) * D2R
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    ra, dec = _eq(lam, 0.0, j)
    return {"ra": ra, "dec": dec, "lam": lam % 360, "gmst": gmst_deg(j)}


def moon(ts: float) -> dict:
    j = jd(ts)
    T = (j - 2451545.0) / 36525
    s = lambda a, b: math.sin((a + b * T) % 360 * D2R)
    c = lambda a, b: math.cos((a + b * T) % 360 * D2R)
    lam = (218.32 + 481267.881 * T + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36)
           + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05)
           - 0.11 * s(186.5, 966404.03)) % 360
    beta = (5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15)
            - 0.17 * s(217.6, -407332.21))
    par = (0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.36)
           + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.74))
    ra, dec = _eq(lam, beta, j)
    return {"ra": ra, "dec": dec, "lam": lam, "beta": beta, "parallax": par,
            "dist_km": 6378.14 / math.sin(par * D2R), "gmst": gmst_deg(j)}


def alt_az(body: dict, lat: float, lon: float) -> tuple[float, float]:
    ha = (body["gmst"] + lon - body["ra"]) * D2R
    la, de = lat * D2R, body["dec"] * D2R
    alt = math.asin(math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha))
    az = math.atan2(-math.sin(ha) * math.cos(de), math.cos(la) * math.sin(de) - math.sin(la) * math.cos(de) * math.cos(ha))
    alt_d = math.degrees(alt)
    if "parallax" in body:                           # topocentric correction for the moon
        alt_d -= body["parallax"] * math.cos(alt)
    return alt_d, (math.degrees(az) + 360) % 360


def subpoint(body: dict) -> tuple[float, float]:
    lon = (body["ra"] - body["gmst"] + 540) % 360 - 180
    return body["dec"], lon


def crossings(fn, lat: float, lon: float, start: float, hours: float, h0: float, step_min: float = 6):
    """Times when fn(ts)'s altitude crosses h0 within [start, start+hours]: list of (ts, rising)."""
    out = []
    step = step_min * 60
    t = start
    prev = alt_az(fn(t), lat, lon)[0] - h0
    end = start + hours * 3600
    while t < end:
        t2 = t + step
        cur = alt_az(fn(t2), lat, lon)[0] - h0
        if (prev < 0) != (cur < 0):
            k = prev / (prev - cur)
            out.append((t + k * step, cur > prev))
        prev, t = cur, t2
    return out


def sun_events(lat: float, lon: float, day_start: float) -> dict:
    """Sunrise/sunset and civil/nautical twilight for the 24 h from day_start."""
    ev = {}
    for name, h0 in (("rise_set", -0.833), ("civil", -6.0), ("nautical", -12.0)):
        for ts, rising in crossings(sun, lat, lon, day_start, 24, h0):
            ev.setdefault(name + ("_up" if rising else "_down"), ts)
    return ev


def moon_events(lat: float, lon: float, start: float, hours: float = 36) -> list[tuple[float, bool]]:
    return crossings(moon, lat, lon, start, hours, 0.125, step_min=10)


def moon_phase(ts: float) -> dict:
    s, m = sun(ts), moon(ts)
    elong = (m["lam"] - s["lam"]) % 360
    illum = (1 - math.cos(elong * D2R)) / 2
    age = elong / 360 * 29.530589
    names = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon",
             "Waning gibbous", "Last quarter", "Waning crescent"]
    return {"illum": illum, "age": age, "waxing": elong < 180, "name": names[int((elong + 22.5) % 360 // 45)]}


def eme_degradation_db(dist_km: float) -> float:
    """Extra EME path loss over the perigee distance (radar equation: loss ~ d^4).
    Distance term only; sky temperature is not included."""
    return 40 * math.log10(dist_km / MOON_PERIGEE_KM)


def local_midnight(ts: float) -> float:
    lt = time.localtime(ts)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
