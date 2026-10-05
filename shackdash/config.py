"""Settings in %APPDATA%\\ShackDash\\config.json."""
from __future__ import annotations

import json
import os
import shutil
import time

from . import __version__

VERSION = __version__
APP_NAME = "SHACKDASH"
APP_TITLE = f"ShackDash v{VERSION}"
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
APP_DIR = os.path.join(_APPDATA, "ShackDash")
OLD_APP_DIR = os.path.join(_APPDATA, "ShackDashboard")    # name before the 2026-10-03 rename to ShackDash
if os.path.isfile(os.path.join(OLD_APP_DIR, "config.json")) and not os.path.exists(os.path.join(APP_DIR, "config.json")):
    try:                                                  # carry the settings and cache across
        shutil.copytree(OLD_APP_DIR, APP_DIR, dirs_exist_ok=True)
    except OSError:
        pass
CACHE_DIR = os.path.join(APP_DIR, "cache")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
USER_AGENT = f"ShackDash/{VERSION} (HamProjects desktop app)"

DEFAULTS = {
    "callsign": "",           # new installs start blank; SETUP opens on first start
    "grid": "",               # (until then, maps and weather use a placeholder position)
    "qth_confirmed": False,
    "cluster": "dxc.ve7cc.net:23",
    "rbn_cw": True,
    "rbn_digi": True,
    "wind_alert_kmh": 60,
    "sat_min_el": 10,
    "theme": "SHACK",
    "zoom": 1.0,
    "licence": "Advanced",
    "bom_state": "VIC",
    "bom_radar": "IDR023",     # Melbourne 128 km
    "aprs_on": True,
    "aprs_km": 150,
    "show_myshack": True,
    "check_updates": True,
    "tab": 0,
    "geometry": None,
}


def load() -> dict:
    """Settings over the defaults. A settings file that exists but cannot be read (locked by a
    backup or sync tool, half-written) is retried for a few seconds; if it still fails, the
    session runs on defaults but never saves, so the real file is not overwritten, and the
    reason is logged to load_error.txt."""
    cfg = dict(DEFAULTS)
    if not os.path.exists(CONFIG_PATH):
        return cfg                                         # first start: nothing to protect
    err = None
    for _ in range(10):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update(json.load(f))
            return cfg
        except (OSError, ValueError) as e:
            err = e
            time.sleep(0.3)
    cfg["_load_failed"] = True
    try:
        with open(os.path.join(APP_DIR, "load_error.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {type(err).__name__}: {err}\n")
    except OSError:
        pass
    return cfg


def save(cfg: dict) -> None:
    if cfg.get("_load_failed"):
        return                                             # never overwrite settings we could not read
    os.makedirs(APP_DIR, exist_ok=True)
    if os.path.exists(CONFIG_PATH):                        # keep the previous good copy
        try:
            shutil.copy2(CONFIG_PATH, os.path.join(APP_DIR, "config.backup.json"))
        except OSError:
            pass
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in cfg.items() if not k.startswith("_")}, f, indent=2)
    os.replace(tmp, CONFIG_PATH)
