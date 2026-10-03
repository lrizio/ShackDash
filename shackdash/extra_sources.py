"""The second batch of free sources (tabs J-N and the H radar): NOAA 27-day
outlook and solar cycle, D-RAP, POTA/WWFF/ParksnPeaks activators, BoM
warnings and radar (anonymous FTP), KiwiSDR receivers, the LoTW activity
list and the ARISS schedules. Parsers run on worker threads."""
from __future__ import annotations

import calendar
import csv
import ftplib
import html
import io
import json
import re
import time
import zipfile

from .net import Source
from .sources import SWPC, MONTHS, iso, jload, p_land, p_png, rss_items

BOM_STATES = {  # state -> warnings RSS product
    "VIC": "IDZ00059.warnings_vic.xml", "NSW": "IDZ00054.warnings_nsw.xml", "QLD": "IDZ00056.warnings_qld.xml",
    "SA": "IDZ00057.warnings_sa.xml", "TAS": "IDZ00058.warnings_tas.xml", "WA": "IDZ00060.warnings_wa.xml",
    "NT": "IDZ00055.warnings_nt.xml"}
RADAR_LAYERS = ("background", "topography", "range", "locations")


# ---- J: the sun --------------------------------------------------------------------------

def p_outlook27(raw: bytes) -> dict:
    text = raw.decode("utf-8", "replace")
    issued = re.search(r":Issued:\s*(.+)", text)
    rows = []
    for m in re.finditer(r"^(\d{4})\s+(\w{3})\s+(\d{1,2})\s+(\d+)\s+(\d+)\s+(\d+)", text, re.M):
        y, mon, d, flux, a, kp = m.groups()
        if mon[:3].title() in MONTHS:
            rows.append((calendar.timegm((int(y), MONTHS[mon[:3].title()], int(d), 0, 0, 0)), int(flux), int(a),
                         int(kp)))
    return {"issued": issued.group(1).strip() if issued else "", "rows": rows}


def _month_ts(tag: str) -> float:
    y, m = tag.split("-")[:2]
    return calendar.timegm((int(y), int(m), 15, 0, 0, 0))


def p_cycle_obs(raw: bytes) -> list:
    out = []
    for r in jload(raw):
        tag = r.get("time-tag", "")
        if tag[:4].isdigit() and int(tag[:4]) >= 1996:
            v = lambda k: r.get(k) if r.get(k) is not None and r.get(k) >= 0 else None
            out.append((_month_ts(tag), v("ssn"), v("smoothed_ssn"), v("f10.7"), v("smoothed_f10.7")))
    return out


def p_cycle_pred(raw: bytes) -> list:
    return [(_month_ts(r["time-tag"]), r.get("predicted_ssn"), r.get("low_ssn"), r.get("high_ssn"),
             r.get("predicted_f10.7")) for r in jload(raw)]


# ---- K: portable activators -----------------------------------------------------------------

def _num(s) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def p_pota(raw: bytes) -> list:
    out = []
    for s in jload(raw):
        khz = _num(s.get("frequency"))
        out.append({"prog": "POTA", "call": (s.get("activator") or "").upper(), "khz": khz,
                    "mode": (s.get("mode") or "").upper(), "ref": s.get("reference") or "",
                    "name": s.get("name") or s.get("parkName") or "", "loc": s.get("locationDesc") or "",
                    "lat": _num(s.get("latitude")), "lon": _num(s.get("longitude")),
                    "t": iso(s["spotTime"]) if s.get("spotTime") else None, "spotter": s.get("spotter") or "",
                    "comment": s.get("comments") or "", "grid": s.get("grid6") or ""})
    return out


def p_wwff(raw: bytes) -> list:
    out = []
    for s in jload(raw):
        out.append({"prog": "WWFF", "call": (s.get("activator") or "").upper(), "khz": _num(s.get("frequency_khz")),
                    "mode": (s.get("mode") or "").upper(), "ref": s.get("reference") or "",
                    "name": s.get("reference_name") or "", "loc": (s.get("reference") or "").split("-")[0],
                    "lat": _num(s.get("latitude")), "lon": _num(s.get("longitude")),
                    "t": float(s["spot_time"]) if s.get("spot_time") else None, "spotter": s.get("spotter") or "",
                    "comment": s.get("remarks") or "", "grid": ""})
    return out


def p_pnp(raw: bytes) -> list:
    """ParksnPeaks: the VK portable spotting site (SOTA, parks, SiOTA...). Times are UTC, frequencies MHz."""
    out = []
    for s in jload(raw):
        mhz = _num(s.get("actFreq"))
        ref = s.get("actSiteID") or s.get("actLocation") or ""
        extra = s.get("WWFFid") or s.get("altLocation") or ""
        out.append({"prog": (s.get("actClass") or "PnP").upper(), "call": (s.get("actCallsign") or "").upper(),
                    "khz": mhz * 1000 if mhz else None, "mode": (s.get("actMode") or "").upper(), "ref": ref,
                    "name": extra, "loc": ref.split("/")[0] if "/" in ref else "", "lat": None, "lon": None,
                    "t": iso(s["actTime"]) if s.get("actTime") else None, "spotter": s.get("actSpoter") or "",
                    "comment": html.unescape(s.get("actComments") or ""), "grid": ""})
    return out


# ---- H: BoM ------------------------------------------------------------------------------------

def p_bom_warn(raw: bytes) -> list:
    out = []
    for it in rss_items(raw):
        title = it["title"]
        m = re.match(r"(\d{2})/(\d{2}):(\d{2})\s+\w+\s+(.*)", title)
        out.append({"title": m.group(4) if m else title, "t": it["t"], "link": it["link"]})
    return out


_radar_mem: dict[str, bytes] = {}            # file name -> png (frames + layers, kept across fetches)


def radar_fetch(radar_id: str, frames: int = 10) -> bytes:
    """Latest radar frames + the static layers from BoM's anonymous FTP, packed in a zip
    (so the hub can cache it like any other download)."""
    ftp = ftplib.FTP("ftp.bom.gov.au", timeout=40)
    try:
        ftp.login()
        ftp.cwd("/anon/gen/radar")
        names = sorted(n for n in ftp.nlst(f"{radar_id}.T.*") if n.endswith(".png"))[-frames:]
        if not names:
            raise ValueError(f"no frames for {radar_id}")

        def get(name):
            if name not in _radar_mem:
                buf = io.BytesIO()
                ftp.retrbinary("RETR " + name, buf.write)
                _radar_mem[name] = buf.getvalue()
            return _radar_mem[name]
        pngs = {n: get(n) for n in names}
        ftp.cwd("/anon/gen/radar_transparencies")
        for layer in RADAR_LAYERS:
            n = f"{radar_id}.{layer}.png"
            try:
                pngs[n] = get(n)
            except ftplib.error_perm:
                pass
    finally:
        try:
            ftp.quit()
        except (OSError, EOFError, ftplib.Error):
            pass
    keep = set(pngs)
    for k in [k for k in _radar_mem if k not in keep]:
        del _radar_mem[k]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for n, data in pngs.items():
            z.writestr(n, data)
    return out.getvalue()


def p_radar(raw: bytes) -> dict:
    z = zipfile.ZipFile(io.BytesIO(raw))
    frames, layers = [], {}
    for n in sorted(z.namelist()):
        m = re.match(r"IDR\w+\.T\.(\d{12})\.png", n)
        if m:
            frames.append((calendar.timegm(time.strptime(m.group(1), "%Y%m%d%H%M")), z.read(n)))
        else:
            layers[n.split(".")[1]] = z.read(n)
    return {"frames": frames, "layers": layers}


# ---- N: tools ----------------------------------------------------------------------------------------

def p_kiwi(raw: bytes) -> list:
    text = raw.decode("utf-8", "replace")
    body = re.sub(r",\s*([\]}])", r"\1", text[text.index("["):text.rindex("]") + 1])
    out = []
    for k in json.loads(body):
        if k.get("offline") != "no" or k.get("status") != "active":
            continue
        m = re.match(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", k.get("gps", ""))
        if not m:
            continue
        lo, _, hi = (k.get("bands") or "0-30000000").partition("-")
        out.append({"name": html.unescape(k.get("name", "")).strip(), "url": k.get("url", ""),
                    "lat": float(m.group(1)), "lon": float(m.group(2)), "loc": k.get("loc", ""),
                    "users": int(k.get("users") or 0), "max": int(k.get("users_max") or 0),
                    "antenna": html.unescape(k.get("antenna", "")), "snr": k.get("snr", ""),
                    "lo": float(lo or 0) / 1e6, "hi": float(hi or 30e6) / 1e6, "grid": k.get("grid", "")})
    return out


def p_lotw(raw: bytes) -> dict:
    """callsign -> date of the last LoTW upload."""
    out = {}
    for row in csv.reader(io.StringIO(raw.decode("latin-1"))):
        if len(row) >= 2:
            out[row[0].upper()] = row[1]
    return out


def p_callook(raw: bytes) -> dict:
    return jload(raw)


# ---- M: ARISS ------------------------------------------------------------------------------------------

def _page_lines(raw: bytes) -> list[str]:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:                  # the ARISS pages mix in Windows-1252 bytes
        s = raw.decode("cp1252", "replace")
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", l).strip() for l in s.splitlines() if l.strip()]


def p_ariss(raw: bytes) -> dict:
    lines = _page_lines(raw)
    asof = next((l for l in lines if l.startswith("As of")), "")
    out = []
    for i, l in enumerate(lines):
        m = re.search(r"Contact is go for:?\s*\w{3}\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*UTC"
                      r"(?:\s+(\d+)\s*deg)?", l)
        if not m:
            continue
        hms = m.group(2) + (":00" if m.group(2).count(":") == 1 else "")
        ts = iso(f"{m.group(1)}T{hms}")
        desc = lines[i - 1] if i else ""
        crew = re.search(r"\(([^()]*[A-Z]{1,2}\d[A-Z]{1,4}[^()]*)\)\s*$", desc)
        via = re.search(r"via\s+([A-Z0-9/]+|TBD)", desc)
        out.append({"t": ts, "desc": re.sub(r"\s*\([^()]*\)\s*$", "", desc), "deg": int(m.group(3)) if m.group(3)
                    else None, "crew": crew.group(1).strip() if crew else "", "via": via.group(1) if via else ""})
    return {"asof": asof, "contacts": out}


def p_sstv(raw: bytes) -> list:
    lines = _page_lines(raw)
    try:
        start = next(i for i, l in enumerate(lines) if l.lower() == "upcoming sstv events") + 1
    except StopIteration:
        start = 0
    events, cur = [], None
    for l in lines[start:start + 80]:
        if re.match(r"^\d{4}-\d{2}-\d{2}|^\d{2}-\d{2}-\d{4}", l):
            cur = {"title": l, "lines": []}
            events.append(cur)
        elif cur is not None and not l.startswith("***"):
            cur["lines"].append(l)
    return events[:6]


# ---- F: reflector host lists ---------------------------------------------------------------------------------

PISTAR = "https://www.pistar.uk/downloads/"
HOST_LISTS = [  # key, network label, file, default port
    ("h_dplus", "D-STAR REF", "DPlus_Hosts.txt", "20001"),
    ("h_dcs", "DCS", "DCS_Hosts.txt", "30051"),
    ("h_dextra", "XRF", "DExtra_Hosts.txt", "30001"),
    ("h_nxdn", "NXDN", "NXDN_Hosts.txt", ""),
    ("h_p25", "P25", "P25_Hosts.txt", ""),
]


def p_hosts(raw: bytes) -> list:
    """Pi-Star host files: 'designator<TAB>host[<TAB>port]' lines, '#' comments. No descriptions."""
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f = line.split()
        if len(f) >= 2:
            out.append({"name": f[0], "host": f[1], "port": f[2] if len(f) > 2 else ""})
    return out


# ---- the catalogue -------------------------------------------------------------------------------------------

def build(cfg: dict) -> list[Source]:
    noaa = "NOAA SWPC (public domain)"

    def warn_url():
        return "https://reg.bom.gov.au/fwo/" + BOM_STATES.get(cfg.get("bom_state", "VIC"), BOM_STATES["VIC"])

    bom = "Bureau of Meteorology (© Commonwealth of Australia, personal use)"
    hosts = [Source(key, f"{label} reflector list", PISTAR + fname, 86400, p_hosts,
                    "Pi-Star host files (pistar.uk)", max_cache_age=30 * 86400)
             for key, label, fname, _port in HOST_LISTS]
    return hosts + [
        Source("outlook27", "27-day space weather outlook", f"{SWPC}/text/27-day-outlook.txt", 6 * 3600,
               p_outlook27, noaa, max_cache_age=14 * 86400),
        Source("cycle_obs", "Solar cycle observed", f"{SWPC}/json/solar-cycle/observed-solar-cycle-indices.json",
               86400, p_cycle_obs, noaa, max_cache_age=60 * 86400),
        Source("cycle_pred", "Solar cycle predicted", f"{SWPC}/json/solar-cycle/predicted-solar-cycle.json",
               86400, p_cycle_pred, noaa, max_cache_age=60 * 86400),
        Source("drap", "D-RAP HF absorption map", f"{SWPC}/images/animations/d-rap/global/latest.png", 600, p_png,
               noaa),
        Source("pota", "POTA activator spots", "https://api.pota.app/spot/activator", 120, p_pota,
               "Parks on the Air (api.pota.app)", max_cache_age=3600),
        Source("wwff", "WWFF spots", "https://spots.wwff.co/static/spots.json", 120, p_wwff,
               "WWFF Spotline (spots.wwff.co)", max_cache_age=3600),
        Source("pnp", "ParksnPeaks spots", "https://www.parksnpeaks.org/api/ALL", 120, p_pnp,
               "ParksnPeaks (parksnpeaks.org)", max_cache_age=3600),
        Source("bom_warn", "BoM weather warnings", warn_url, 600, p_bom_warn, bom),
        Source("radar", "BoM rain radar (FTP)", "ftp://ftp.bom.gov.au/anon/gen/radar/", 360, p_radar, bom,
               max_cache_age=3 * 3600, fetch=lambda: radar_fetch(cfg.get("bom_radar", "IDR023").strip().upper())),
        Source("land50", "Coastlines (regional maps)", "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_50m_land.geojson", 30 * 86400, p_land, "Natural Earth (public domain)",
               max_cache_age=10 ** 9, timeout=90),
        Source("kiwi", "KiwiSDR public receivers", "http://rx.linkfanel.net/kiwisdr_com.js", 6 * 3600, p_kiwi,
               "kiwisdr.com list via rx.linkfanel.net", max_cache_age=7 * 86400, timeout=90),
        Source("lotw", "LoTW user activity", "https://lotw.arrl.org/lotw-user-activity.csv", 7 * 86400, p_lotw,
               "ARRL Logbook of The World", max_cache_age=30 * 86400, timeout=120, delay=60),
        Source("ariss", "ARISS school contacts", "https://www.ariss.org/upcoming-educational-contacts.html",
               6 * 3600, p_ariss, "ARISS (ariss.org)", headers={"User-Agent": "Mozilla/5.0"}),
        Source("sstv", "ARISS SSTV events", "https://www.ariss.org/upcoming-sstv-events.html", 6 * 3600, p_sstv,
               "ARISS (ariss.org)", headers={"User-Agent": "Mozilla/5.0"}),
    ]
