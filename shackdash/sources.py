"""Every free internet source the dashboard reads, with its parser. Parsers
run on worker threads and return plain Python data."""
from __future__ import annotations

import calendar
import glob
import html
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import config
from .geo import Cty, grid_to_latlon
from .net import Source, http_get

SWPC = "https://services.swpc.noaa.gov"
MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}


def iso(ts: str) -> float:
    ts = ts.strip().replace(" ", "T").rstrip("Z")
    if "." in ts:
        ts = ts.split(".")[0]
    return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))


def jload(raw: bytes):
    return json.loads(raw.decode("utf-8", "replace"))


def strip_html(s: str) -> str:
    s = re.sub(r"<(br|p|/p|li)[^>]*>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


# ---- A: space weather ---------------------------------------------------------------

def p_hamqsl(raw: bytes) -> dict:
    root = ET.fromstring(raw.decode("utf-8", "replace").strip())
    sd = root.find("solardata")
    g = lambda tag: (sd.findtext(tag) or "").strip()
    out = {k: g(k) for k in ("updated", "solarflux", "aindex", "kindex", "kindexnt", "xray", "sunspots",
                             "heliumline", "protonflux", "electonflux", "aurora", "normalization",
                             "latdegree", "solarwind", "magneticfield", "geomagfield", "signalnoise", "fof2",
                             "muffactor", "muf")}
    bands = {}
    cc, vc = sd.find("calculatedconditions"), sd.find("calculatedvhfconditions")
    for b in (cc if cc is not None else []):
        bands.setdefault(b.get("name"), {})[b.get("time")] = (b.text or "").strip()
    out["bands"] = bands
    out["vhf"] = [(p.get("name"), p.get("location"), (p.text or "").strip())
                  for p in (vc if vc is not None else [])]
    return out


def p_kp(raw: bytes) -> list:
    out = []
    for row in jload(raw):
        if isinstance(row, dict):
            out.append((iso(row["time_tag"]), float(row["kp"]), row.get("observed", "observed")))
    return out


def p_xray(raw: bytes) -> dict:
    long_, short = ([], []), ([], [])
    for r in jload(raw):
        f = r.get("flux")
        if f is None:
            continue
        tgt = long_ if r.get("energy") == "0.1-0.8nm" else short
        tgt[0].append(iso(r["time_tag"]))
        tgt[1].append(float(f))
    return {"long": long_, "short": short}


def xray_class(flux: float | None) -> str:
    if not flux or flux <= 0:
        return "--"
    for letter, base in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)):
        if flux >= base:
            return f"{letter}{flux / base:.1f}"
    return f"A{flux / 1e-8:.1f}"


def _rtsw(raw: bytes, fields: tuple[str, ...], bucket: int = 300) -> dict:
    """Active-spacecraft 1-minute data averaged into 5-minute buckets."""
    acc: dict[int, list] = {}
    for r in jload(raw):
        if not r.get("active"):
            continue
        b = int(iso(r["time_tag"]) // bucket * bucket)
        slot = acc.setdefault(b, [[] for _ in fields])
        for i, f in enumerate(fields):
            v = r.get(f)
            if v is not None:
                slot[i].append(float(v))
    ts = sorted(acc)
    out = {"t": ts}
    for i, f in enumerate(fields):
        out[f] = [(sum(acc[t][i]) / len(acc[t][i])) if acc[t][i] else None for t in ts]
    return out


def p_wind(raw: bytes) -> dict:
    return _rtsw(raw, ("proton_speed", "proton_density"))


def p_mag(raw: bytes) -> dict:
    return _rtsw(raw, ("bz_gsm", "bt"))


def p_protons(raw: bytes) -> tuple:
    t, v = [], []
    for r in jload(raw):
        if r.get("energy") == ">=10 MeV" and r.get("flux") is not None:
            t.append(iso(r["time_tag"]))
            v.append(float(r["flux"]))
    return t, v


def p_alerts(raw: bytes) -> list:
    out = []
    for r in jload(raw)[:40]:
        msg = r.get("message", "").replace("\r", "")
        lines = [l.strip() for l in msg.split("\n") if l.strip()]
        head = next((l for l in lines if l.startswith(("ALERT", "WARNING", "WATCH", "SUMMARY", "EXTENDED",
                                                         "CONTINUED", "CANCEL"))), lines[2] if len(lines) > 2 else "")
        out.append({"t": iso(r["issue_datetime"]), "id": r.get("product_id", ""), "head": head, "text": msg})
    return out


def p_scales(raw: bytes) -> dict:
    return jload(raw)


def p_ionosondes(raw: bytes) -> list:
    out = []
    for r in jload(raw):
        st = r.get("station", {})
        try:
            lat, lon = float(st["latitude"]), float(st["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"name": st.get("name", "?"), "code": st.get("code", ""), "lat": lat,
                    "lon": (lon + 180) % 360 - 180, "t": iso(r["time"]), "mufd": r.get("mufd"),
                    "fof2": r.get("fof2"), "hmf2": r.get("hmf2"), "cs": r.get("cs")})
    return out


def p_aurora(raw: bytes) -> dict:
    import numpy as np
    d = jload(raw)
    grid = np.zeros((181, 360), dtype=np.float32)          # [lat+90, lon]
    for lon, lat, v in d["coordinates"]:
        grid[int(lat) + 90, int(lon) % 360] = v
    return {"grid": grid, "obs": d.get("Observation Time", ""), "fc": d.get("Forecast Time", "")}


# ---- B: live activity --------------------------------------------------------------------

def p_psk(raw: bytes) -> list:
    root = ET.fromstring(raw)
    out = []
    for r in root.iter("receptionReport"):
        a = r.attrib
        try:
            out.append({"rx": a.get("receiverCallsign", ""), "rx_loc": a.get("receiverLocator", ""),
                        "tx": a.get("senderCallsign", ""), "tx_loc": a.get("senderLocator", ""),
                        "f": int(a.get("frequency", "0") or 0), "t": int(a.get("flowStartSeconds", "0")),
                        "mode": a.get("mode", ""), "snr": a.get("sNR", ""),
                        "rx_dxcc": a.get("receiverDXCC", ""), "tx_dxcc": a.get("senderDXCC", "")})
        except ValueError:
            continue
    return out


def p_wspr(raw: bytes) -> list:
    return jload(raw).get("data", [])


# ---- C/G: maps ----------------------------------------------------------------------------

def p_land(raw: bytes) -> list:
    polys = []
    for feat in jload(raw)["features"]:
        geom = feat["geometry"]
        rings = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in rings:
            polys.append([(float(x), float(y)) for x, y in poly[0]])
    return polys


def p_cty(raw: bytes) -> Cty:
    """The front page names the latest cty-NNNN.zip; the site refuses hot-links without a referer."""
    page = raw.decode("utf-8", "replace")
    links = re.findall(r'href="(https://www\.country-files\.com/cty/download/(\d+)/cty-\d+\.zip)"', page)
    cached = sorted(glob.glob(os.path.join(config.CACHE_DIR, "cty-*.zip")))
    if links:
        url, ver = max(links, key=lambda l: int(l[1]))
        path = os.path.join(config.CACHE_DIR, f"cty-{ver}.zip")
        if not os.path.exists(path):
            data = http_get(url, {"Referer": "https://www.country-files.com/",
                                  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with open(path, "wb") as f:
                f.write(data)
            for old in cached:
                if old != path:
                    try:
                        os.remove(old)
                    except OSError:
                        pass
        cached = [path]
    if not cached:
        raise ValueError("country file not available")
    with open(cached[-1], "rb") as f:
        return Cty.from_zip(f.read())


def p_tropo_index(raw: bytes) -> list:
    """[(name, valid_ts, url)]. The ?vYYYYMMDD tag is the model run day; +006 h is valid at 18z,
    so the run is 12z that day."""
    page = raw.decode("utf-8", "replace")
    found = dict(re.findall(r"tr_map/fcst/(aus\d{3})\.png(\?v\d{8})?", page))
    out = []
    for name, tag in sorted(found.items(), key=lambda kv: int(kv[0][3:])):
        valid = None
        if tag:
            base = calendar.timegm(time.strptime(tag[2:], "%Y%m%d")) + 12 * 3600
            valid = base + int(name[3:]) * 3600
        out.append((name, valid, f"https://www.dxinfocentre.com/tr_map/fcst/{name}.png{tag}"))
    return out


def p_png(raw: bytes) -> bytes:
    return raw


# ---- D: satellites ------------------------------------------------------------------------

def p_tle(raw: bytes) -> list:
    from .sats import parse_tle
    return parse_tle(raw.decode("utf-8", "replace"))


def p_transmitters(raw: bytes) -> dict:
    out: dict[int, list] = {}
    for t in jload(raw):
        if not t.get("alive") or t.get("status") != "active" or not t.get("norad_cat_id"):
            continue
        if t.get("service") not in ("Amateur", None):
            continue
        out.setdefault(int(t["norad_cat_id"]), []).append({
            "desc": t.get("description", ""), "down": t.get("downlink_low"), "down_hi": t.get("downlink_high"),
            "up": t.get("uplink_low"), "up_hi": t.get("uplink_high"), "mode": t.get("mode") or "",
            "invert": bool(t.get("invert"))})
    return out


def p_satnogs_obs(raw: bytes) -> list:
    out = []
    for o in jload(raw)[:80]:
        out.append({"t": iso(o["start"]), "end": iso(o["end"]), "norad": o.get("norad_cat_id"),
                    "station": o.get("station_name") or str(o.get("ground_station", "")),
                    "observer": o.get("observer", ""), "status": o.get("status", ""),
                    "lat": o.get("station_lat"), "lon": o.get("station_lng"), "id": o.get("id"),
                    "mode": o.get("transmitter_mode") or "", "desc": o.get("transmitter_description") or ""})
    return out


# ---- E: calendar ----------------------------------------------------------------------------

def _tag(block: str, tag: str) -> str:
    m = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", block, re.S | re.I)
    if not m:
        return ""
    v = m.group(1).strip()
    c = re.fullmatch(r"<!\[CDATA\[(.*?)\]\]>", v, re.S)
    return c.group(1) if c else v


def rss_items(raw: bytes) -> list[dict]:
    """Lenient RSS reader: several ham feeds put raw HTML inside their XML, so no XML parser."""
    text = raw.decode("utf-8", "replace")
    chan = re.search(r"<link>(https?://[^/<]+)", text)
    site = (chan.group(1) if chan else "") + "/"
    items = []
    for block in re.findall(r"<item(?:\s[^>]*)?>(.*?)</item>", text, re.S | re.I):
        ts = None
        pub = _tag(block, "pubDate") or _tag(block, "dc:date")
        if pub:
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except (TypeError, ValueError):
                try:
                    ts = iso(pub[:19])
                except ValueError:
                    pass
        desc = _tag(block, "description") or _tag(block, "content:encoded")
        desc = strip_html(html.unescape(desc) if "&lt;" in desc else desc)
        title = html.unescape(strip_html(_tag(block, "title")))
        if not title:                            # WIA's feed leaves <title> empty: use the first line
            title = desc.split("\n", 1)[0][:140]
        link = html.unescape(_tag(block, "link"))
        guid = _tag(block, "guid")
        if not link and guid:
            link = guid if guid.startswith("http") else urllib.parse.urljoin(
                site, re.sub(r"/texts$", "/", guid.lstrip("/")))
        items.append({"title": title, "link": link, "desc": desc, "t": ts})
    items.sort(key=lambda i: i["t"] or 0, reverse=True)
    return items


def _contest_time(s: str, year: int) -> float | None:
    m = re.match(r"(\d{2})(\d{2})Z,\s*(\w{3})\s+(\d+)", s.strip())
    if not m:
        return None
    hh, mm, mon, day = int(m[1]), int(m[2]), MONTHS.get(m[3][:3].title()), int(m[4])
    if not mon:
        return None
    return calendar.timegm((year, mon, day, 0, 0, 0)) + hh * 3600 + mm * 60


def p_contests(raw: bytes) -> list:
    now = time.time()
    y = time.gmtime(now).tm_year
    out = []
    for it in rss_items(raw):
        start = end = None
        parts = re.split(r"\s+to\s+", it["desc"].split("\n")[0])
        if len(parts) == 2:
            start, end = _contest_time(parts[0], y), _contest_time(parts[1], y)
            if start and start < now - 200 * 86400:            # December listing a January contest
                start, end = _contest_time(parts[0], y + 1), _contest_time(parts[1], y + 1)
            if start and end and end < start:
                end = _contest_time(parts[1], y + 1)
        out.append({**it, "start": start, "end": end})
    return out


def _dx_dates(s: str):
    m = re.match(r"(\w{3})\s+(\d+)(?:,\s*(\d{4}))?\s*-\s*(?:(\w{3})\s+)?(\d+),\s*(\d{4})", s.strip())
    if not m:
        return None, None
    m1, d1, y1, m2, d2, y2 = m.groups()
    mo1, mo2 = MONTHS.get(m1[:3].title()), MONTHS.get((m2 or m1)[:3].title())
    if not mo1 or not mo2:
        return None, None
    y2 = int(y2)
    y1 = int(y1) if y1 else (y2 if mo1 <= mo2 else y2 - 1)
    return calendar.timegm((y1, mo1, int(d1), 0, 0, 0)), calendar.timegm((y2, mo2, int(d2), 23, 59, 0))


def p_dxped(raw: bytes) -> list:
    out = []
    for it in rss_items(raw):
        bits = [b.strip() for b in it["title"].split(" -- ")]
        entity, dates = (bits[0].split(":", 1) + [""])[:2]
        start, end = _dx_dates(dates)
        qsl = next((b[len("QSL via:"):].strip() for b in bits if b.startswith("QSL via")), "")
        out.append({"entity": entity.strip(), "dates": dates.strip(), "call": bits[1] if len(bits) > 1 else "",
                    "qsl": qsl, "start": start, "end": end, "link": it["link"], "desc": it["desc"]})
    return out


def p_mostwanted(raw: bytes) -> list:
    d = jload(raw)
    return sorted(((int(k), int(v)) for k, v in d.items()), key=lambda kv: kv[0])


# ---- F: digital voice -----------------------------------------------------------------------

def p_xlx(raw: bytes) -> list:
    text = raw.decode("utf-8", "replace")
    out = []
    for block in re.findall(r"<reflector>(.*?)</reflector>", text, re.S):
        g = lambda tag: html.unescape(_tag(block, tag))
        out.append({"name": g("name"), "country": g("country"), "comment": g("comment"),
                    "dashboard": g("dashboardurl"), "uptime": g("uptime"), "lastcontact": g("lastcontact")})
    return out


def p_bm_tg(raw: bytes) -> list:
    d = jload(raw)
    return sorted(((int(k), v) for k, v in d.items() if k.isdigit()), key=lambda kv: kv[0])


def p_ysf(raw: bytes) -> list:
    """Pi-Star YSF_Hosts.txt: id;name;description;host;port;..."""
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("#") or ";" not in line:
            continue
        f = line.split(";")
        if len(f) >= 5:
            out.append({"id": f[0], "name": f[1], "description": f[2], "host": f"{f[3]}:{f[4]}"})
    return out


# ---- H: weather ---------------------------------------------------------------------------

def p_json(raw: bytes):
    return jload(raw)


# ---- the catalogue ---------------------------------------------------------------------------

NEWS_FEEDS = [
    ("news_wia", "WIA News", "https://www.wia.org.au/rss/"),
    ("news_arrl", "ARRL News", "https://www.arrl.org/news/rss"),
    ("news_arnl", "Amateur Radio Newsline", "https://www.arnewsline.org/?format=rss"),
    ("news_dxw", "DX-World", "https://www.dx-world.net/feed/"),
]


def build(cfg: dict) -> list[Source]:
    def latlon():
        return grid_to_latlon(cfg.get("grid", "QF22")) or (-37.5, 145.0)

    def call():
        return urllib.parse.quote(cfg.get("callsign", "").upper())

    def wspr_url():
        c = cfg.get("callsign", "").upper().replace("'", "")
        q = ("SELECT time, band, tx_sign, tx_loc, rx_sign, rx_loc, frequency, snr, distance, azimuth, power "
             f"FROM wspr.rx WHERE (tx_sign='{c}' OR rx_sign='{c}') AND time > now() - INTERVAL 24 HOUR "
             "ORDER BY time DESC LIMIT 300 FORMAT JSON")
        return "https://db1.wspr.live/?query=" + urllib.parse.quote(q)

    def weather_url():
        lat, lon = latlon()
        return ("https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat:.3f}&longitude={lon:.3f}&timezone=auto&forecast_days=3&wind_speed_unit=kmh"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,"
                "cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
                "&hourly=temperature_2m,precipitation_probability,precipitation,weather_code,wind_speed_10m,"
                "wind_gusts_10m,cape"
                "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max,"
                "sunrise,sunset")

    def grid_field():
        return (cfg.get("grid", "QF22")[:2]).upper()

    noaa = "NOAA SWPC (public domain)"
    src = [
        Source("hamqsl", "Solar summary + band conditions", "https://www.hamqsl.com/solarxml.php", 900, p_hamqsl,
               "Solar-terrestrial data courtesy of N0NBH, hamqsl.com"),
        Source("kp", "Planetary Kp (observed + forecast)", f"{SWPC}/products/noaa-planetary-k-index-forecast.json",
               900, p_kp, noaa),
        Source("xray", "GOES X-ray flux (24 h)", f"{SWPC}/json/goes/primary/xrays-1-day.json", 300, p_xray, noaa),
        Source("wind", "Solar wind plasma (RTSW)", f"{SWPC}/json/rtsw/rtsw_wind_1m.json", 300, p_wind, noaa),
        Source("mag", "Interplanetary magnetic field (RTSW)", f"{SWPC}/json/rtsw/rtsw_mag_1m.json", 300, p_mag, noaa),
        Source("protons", "GOES integral protons (24 h)", f"{SWPC}/json/goes/primary/integral-protons-1-day.json",
               600, p_protons, noaa),
        Source("alerts", "SWPC alerts, watches, warnings", f"{SWPC}/products/alerts.json", 600, p_alerts, noaa),
        Source("scales", "NOAA R/S/G scales", f"{SWPC}/products/noaa-scales.json", 600, p_scales, noaa),
        Source("ionosondes", "Ionosonde MUF / foF2", "https://prop.kc2g.com/api/stations.json", 600, p_ionosondes,
               "prop.kc2g.com (KC2G), GIRO ionosonde network"),
        Source("aurora", "OVATION aurora forecast", f"{SWPC}/json/ovation_aurora_latest.json", 900, p_aurora, noaa),
        Source("psk_me", "PSKReporter: who hears me", lambda: "https://retrieve.pskreporter.info/query?"
               f"senderCallsign={call()}&flowStartSeconds=-3600&rronly=1", 900, p_psk, "PSKReporter (N1DQ)",
               timeout=90, enabled=lambda: bool(call())),
        Source("psk_grid", "PSKReporter: my grid field", lambda: "https://retrieve.pskreporter.info/query?"
               f"callsign={grid_field()}&modify=grid&flowStartSeconds=-3600&rronly=1", 900, p_psk,
               "PSKReporter (N1DQ)", timeout=120, delay=45, enabled=lambda: len(grid_field()) == 2),
        Source("wspr", "WSPR spots (my call, 24 h)", wspr_url, 600, p_wspr, "wspr.live (WSPRnet mirror)",
               enabled=lambda: bool(call())),
        Source("land", "World coastlines", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_110m_land.geojson", 30 * 86400, p_land, "Natural Earth (public domain)",
               max_cache_age=10 ** 9),
        Source("cty", "Callsign prefix database", "https://www.country-files.com/", 7 * 86400, p_cty,
               "AD1C country files, country-files.com", max_cache_age=10 ** 9,
               headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}),
        Source("tle", "Amateur satellite TLEs", "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=tle",
               6 * 3600, p_tle, "CelesTrak (T.S. Kelso)", max_cache_age=7 * 86400),
        Source("sat_tx", "Satellite transmitters", "https://db.satnogs.org/api/transmitters/?format=json",
               86400, p_transmitters, "SatNOGS DB (Libre Space Foundation, CC BY-SA)", max_cache_age=30 * 86400,
               timeout=90),
        Source("satnogs_obs", "SatNOGS recent good observations",
               "https://network.satnogs.org/api/observations/?status=good&format=json", 900, p_satnogs_obs,
               "SatNOGS Network (Libre Space Foundation)"),
        Source("contests", "Contest calendar", "https://www.contestcalendar.com/calendar.rss", 6 * 3600, p_contests,
               "WA7BNM Contest Calendar"),
        Source("dxped", "Announced DX operations", "https://www.ng3k.com/adxo.xml", 6 * 3600, p_dxped,
               "NG3K Announced DX Operations"),
        Source("mostwanted", "DXCC most wanted", "https://clublog.org/mostwanted.php?api=1", 86400, p_mostwanted,
               "Club Log (G7VJR)"),
        Source("xlx", "XLX / D-STAR reflectors", "http://xlxapi.rlx.lu/api.php?do=GetReflectorList", 1800, p_xlx,
               "XLX API (xlxapi.rlx.lu)"),
        Source("bm_tg", "BrandMeister talkgroups", "https://api.brandmeister.network/v2/talkgroup", 86400, p_bm_tg,
               "BrandMeister API"),
        Source("ysf", "YSF reflector list", "https://www.pistar.uk/downloads/YSF_Hosts.txt", 6 * 3600, p_ysf,
               "Pi-Star host files (data from DVRef)", max_cache_age=30 * 86400),
        Source("tropo_idx", "Hepburn tropo forecast (index)", "https://www.dxinfocentre.com/tropo_aus.html",
               3 * 3600, p_tropo_index, "William Hepburn, dxinfocentre.com (images, personal use)"),
        Source("weather", "Local weather + forecast", weather_url, 900, p_json, "Open-Meteo.com (CC BY 4.0)"),
    ]
    for key, name, url in NEWS_FEEDS:
        src.append(Source(key, name, url, 3600, rss_items, name))
    return src
