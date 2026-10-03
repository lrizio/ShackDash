"""Where is a callsign? The country file only knows each DXCC entity's centre,
so every VK call would be 'in the middle of Australia'. This module ranks
better sources:

    6  APRS position heard on tab L (GPS / station setting)
    5  the station's own Maidenhead locator (its FT8/WSPR software sends it; via PSKReporter / WSPR)
    4  the US FCC licence address (callook.info)
    2  call area: the main city of the numbered call area (VK3 = Melbourne ...)
    1  the DXCC entity centre from the country file
"""
from __future__ import annotations

import re

from .geo import grid_to_latlon

# call-area digit -> (lat, lon, name); the main city of each area stands in for "somewhere in it"
AREAS = {
    "VK": {"1": (-35.28, 149.13, "VK1 ACT (Canberra)"), "2": (-33.87, 151.21, "VK2 NSW (Sydney)"),
           "3": (-37.81, 144.96, "VK3 Victoria (Melbourne)"), "4": (-27.47, 153.03, "VK4 Queensland (Brisbane)"),
           "5": (-34.93, 138.60, "VK5 South Australia (Adelaide)"), "6": (-31.95, 115.86, "VK6 WA (Perth)"),
           "7": (-42.88, 147.33, "VK7 Tasmania (Hobart)"), "8": (-12.46, 130.84, "VK8 NT (Darwin)")},
    "ZL": {"1": (-36.85, 174.76, "ZL1 (Auckland)"), "2": (-41.29, 174.78, "ZL2 (Wellington)"),
           "3": (-43.53, 172.64, "ZL3 (Christchurch)"), "4": (-45.87, 170.50, "ZL4 (Dunedin)")},
    "VE": {"1": (44.65, -63.57, "VE1 Nova Scotia (Halifax)"), "2": (45.50, -73.57, "VE2 Quebec (Montreal)"),
           "3": (43.65, -79.38, "VE3 Ontario (Toronto)"), "4": (49.90, -97.14, "VE4 Manitoba (Winnipeg)"),
           "5": (50.45, -104.61, "VE5 Saskatchewan (Regina)"), "6": (51.05, -114.07, "VE6 Alberta (Calgary)"),
           "7": (49.28, -123.12, "VE7 British Columbia (Vancouver)"), "8": (62.45, -114.37, "VE8 NWT (Yellowknife)"),
           "9": (45.96, -66.64, "VE9 New Brunswick (Fredericton)")},
    "JA": {"1": (35.68, 139.69, "JA1 Kanto (Tokyo)"), "2": (35.18, 136.91, "JA2 Tokai (Nagoya)"),
           "3": (34.69, 135.50, "JA3 Kansai (Osaka)"), "4": (34.39, 132.46, "JA4 Chugoku (Hiroshima)"),
           "5": (33.84, 132.77, "JA5 Shikoku (Matsuyama)"), "6": (33.59, 130.40, "JA6 Kyushu (Fukuoka)"),
           "7": (38.27, 140.87, "JA7 Tohoku (Sendai)"), "8": (43.06, 141.35, "JA8 Hokkaido (Sapporo)"),
           "9": (36.56, 136.66, "JA9 Hokuriku (Kanazawa)"), "0": (37.92, 139.04, "JA0 Shinetsu (Niigata)")},
    # US districts: calls no longer change when people move, so this is only a rough guess
    "US": {"1": (42.36, -71.06, "W1 New England (Boston)"), "2": (40.71, -74.00, "W2 NY/NJ (New York)"),
           "3": (39.95, -75.17, "W3 PA/MD/DE/DC (Philadelphia)"), "4": (33.75, -84.39, "W4 south-east (Atlanta)"),
           "5": (32.78, -96.80, "W5 south central (Dallas)"), "6": (34.05, -118.24, "W6 California (Los Angeles)"),
           "7": (40.76, -111.89, "W7 north-west/mountain (Salt Lake City)"),
           "8": (39.96, -83.00, "W8 MI/OH/WV (Columbus)"), "9": (41.88, -87.63, "W9 IL/IN/WI (Chicago)"),
           "0": (39.10, -94.58, "W0 central (Kansas City)")},
}
FAMILY_BY_ADIF = {150: "VK", 170: "ZL", 1: "VE", 339: "JA", 291: "US"}


def _base(call: str) -> tuple[str, str | None]:
    """(home call, portable-area digit) from e.g. VK3EI, VK2/VK3EI, VK3EI/2, VK3EI/P."""
    call = call.upper().strip()
    parts = [p for p in call.split("/") if p]
    home = max(parts, key=len) if parts else call
    digit = None
    for p in parts:
        if p != home and re.fullmatch(r"\d", p):
            digit = p                                    # VK3EI/2 = operating in VK2
        elif p != home and re.fullmatch(r"[A-Z]{1,2}\d", p):
            digit = p[-1]                                # VK2/VK3EI
    return home, digit


def call_area(call: str, adif: int | None):
    """(lat, lon, name) of the call area, for the entities in AREAS, else None."""
    fam = FAMILY_BY_ADIF.get(adif if adif is not None else -1)
    if not fam:
        return None
    home, digit = _base(call)
    if digit is None:
        m = re.match(r"[A-Z0-9]?[A-Z]{1,2}(\d)", home)
        if not m:
            return None
        digit = m.group(1)
    return AREAS[fam].get(digit)


def same_station(name: str, call: str) -> bool:
    """APRS/PSK names carry SSIDs and suffixes: VK3EI-9, VK3EI/P, VK3EI."""
    base = _base(call)[0]
    n = name.upper().split("-")[0]
    return n == base or _base(n)[0] == base


def _grid_hit(loc: str, what: str):
    ll = grid_to_latlon(loc[:6]) if loc and len(loc) >= 4 else None
    return (5, ll[0], ll[1], f"their locator {loc[:6]} ({what})") if ll else None


def from_cached(call: str, hub_data: dict, aprs: dict):
    """Best (rank, lat, lon, source) from data the dashboard already holds, or None."""
    for st in aprs.values():                             # tab L: real positions
        if "lat" in st and st.get("kind") != "object" and same_station(st["name"], call):
            return (6, st["lat"], st["lon"], f"APRS position of {st['name']}")
    for key in ("psk_me", "psk_grid"):                   # PSKReporter reports already downloaded
        for r in hub_data.get(key) or []:
            for who, loc in ((r["tx"], r["tx_loc"]), (r["rx"], r["rx_loc"])):
                if loc and same_station(who, call):
                    hit = _grid_hit(loc, "sent by their own software, via PSKReporter")
                    if hit:
                        return hit
    for r in hub_data.get("wspr") or []:
        for who, loc in ((r.get("tx_sign", ""), r.get("tx_loc", "")), (r.get("rx_sign", ""), r.get("rx_loc", ""))):
            if loc and same_station(who, call):
                hit = _grid_hit(loc, "their WSPR station")
                if hit:
                    return hit
    return None


def psk_locator(reports: list, call: str):
    """The locator a station used, from a PSKReporter query for it (its most detailed one)."""
    locs = [r["tx_loc"] for r in reports if r.get("tx_loc") and same_station(r["tx"], call)]
    locs += [r["rx_loc"] for r in reports if r.get("rx_loc") and same_station(r["rx"], call)]
    if not locs:
        return None
    loc = max(locs, key=lambda l: (min(len(l), 6), locs.count(l)))
    return _grid_hit(loc, "sent by their own software, via PSKReporter")
