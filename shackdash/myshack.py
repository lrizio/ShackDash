"""MY SHACK: the operator's own LAN gear. Each device has a type that says
how to ask it for its state:

    wpsd    WPSD / Pi-Star hotspot running m5status.php (link, last heard, CPU temp)
    matrix  HF Matrix relay box: GET /api/status (radio -> antenna map, temps, alarms);
            found by its UDP discovery beacon on port 51500 as well as by name
    clock   Shack Clock: GET /status (NTP sync age, brightness, WiFi signal, uptime)
    hotspotmon  Hotspot Monitor (Nextion edition): GET /names; a rename made on its touch keyboard
            relabels the matching WPSD hotspot here too (matched by hostname, mDNS name or address)
    http    anything with a web page: up/down + response time
    ping    anything else on the LAN: ICMP echo

A host that stops resolving falls back to the last address it answered on,
which is saved back to the settings so the list heals itself."""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from . import config
from concurrent.futures import ThreadPoolExecutor

TYPES = ["wpsd", "matrix", "clock", "hotspotmon", "http", "ping"]
TYPE_NAMES = {"wpsd": "WPSD hotspot", "matrix": "HF matrix box", "clock": "Shack Clock",
              "hotspotmon": "Hotspot Monitor", "http": "web device", "ping": "LAN device"}
BEACON_PORT = 51500



class BeaconListener:
    """Collects the HF Matrix boxes' {"hf":"<hostname>","port":80} broadcasts."""

    def __init__(self):
        self.seen: dict[str, tuple[str, float]] = {}
        self.ok = False
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="matrix-beacons").start()

    def _run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", BEACON_PORT))
            s.settimeout(2)
            self.ok = True
        except OSError:
            return
        while not self._stop.is_set():
            try:
                data, addr = s.recvfrom(512)
                name = json.loads(data.decode("utf-8", "replace")).get("hf")
                if name:
                    self.seen[str(name).lower()] = (addr[0], time.time())
            except (socket.timeout, ValueError, AttributeError):
                continue
            except OSError:
                time.sleep(2)

    def lookup(self, host: str) -> str | None:
        hit = self.seen.get(host.lower().removesuffix(".local"))
        return hit[0] if hit and time.time() - hit[1] < 60 else None

    def stop(self):
        self._stop.set()


def _resolve(dev: dict, beacons: BeaconListener | None) -> tuple[str | None, str]:
    host = (dev.get("host") or "").strip()
    if dev.get("type") == "matrix" and beacons:
        ip = beacons.lookup(host)
        if ip:
            return ip, "beacon"
    if host:
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", host):
            return host, "fixed"
        name = host if "." in host else host + ".local"
        try:
            return socket.gethostbyname(name), "name"
        except OSError:
            pass
    return (dev.get("ip") or None), "last known"


def _get(url: str, timeout: float = 4) -> tuple[bytes, float]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(200_000)
    return data, (time.perf_counter() - t0) * 1000


def _ping(ip: str) -> float | None:
    flags = 0x08000000 if sys.platform == "win32" else 0            # CREATE_NO_WINDOW
    args = ["ping", "-n", "1", "-w", "1500", ip] if sys.platform == "win32" else ["ping", "-c", "1", "-W", "2", ip]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, creationflags=flags).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "TTL=" not in out.upper():
        return None
    m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out)
    return float(m.group(1)) if m else 0.0


def probe(dev: dict, beacons: BeaconListener | None) -> dict:
    ip, how = _resolve(dev, beacons)
    res = {"name": dev.get("name", "?"), "type": dev.get("type", "ping"), "ip": ip, "how": how, "up": False,
           "ms": None, "data": None, "error": "", "t": time.time()}
    if not ip:
        res["error"] = "no address (name did not resolve and none remembered)"
        return res
    kind = res["type"]
    try:
        if kind == "wpsd":
            raw, ms = _get(f"http://{ip}/m5status.php")
            res["data"], res["ms"], res["up"] = json.loads(raw.decode("utf-8", "replace")), ms, True
        elif kind in ("matrix", "clock", "hotspotmon"):
            path = {"matrix": "/api/status", "clock": "/status", "hotspotmon": "/names"}[kind]
            raw, ms = _get(f"http://{ip}{path}")
            res["data"], res["ms"], res["up"] = json.loads(raw.decode("utf-8", "replace")), ms, True
        elif kind == "http":
            _raw, ms = _get(f"http://{ip}/")
            res["ms"], res["up"] = ms, True
        else:
            ms = _ping(ip)
            res["ms"], res["up"] = ms, ms is not None
            if ms is None:
                res["error"] = "no reply to ping"
    except (OSError, ValueError) as e:
        res["error"] = f"{type(e).__name__}: {e}"[:160]
        if kind in ("wpsd", "matrix", "clock", "hotspotmon", "http"):       # the web side is down: is the box itself alive?
            ms = _ping(ip)
            if ms is not None:
                res["error"] = "answers ping, but its web service did not reply"
                res["ms"] = ms
    return res


def _short(host) -> str:
    return str(host or "").strip().lower().removesuffix(".local")


def _apply_monitor_names(devices: list[dict], results: list[dict]):
    """Carry a rename made on a Hotspot Monitor's touch keyboard over to the matching WPSD hotspot.
    Only a CHANGE on the monitor is copied: each device remembers the monitor name it last took
    (dev["mon_name"]), so a name typed in EDIT DEVICES stays until the hotspot is renamed on the
    monitor again -- whichever rename was made last wins. Sets res["renamed"] when the shown name
    changes and res["mon_name"] when there is a monitor name to remember."""
    names = []                                     # (keys identifying the hotspot, name)
    for r in results:
        if r["type"] == "hotspotmon" and r["up"] and isinstance(r["data"], dict):
            for h in r["data"].get("hotspots") or []:
                keys = {_short(h.get("mdns")), _short(h.get("hostname")), str(h.get("ip") or "")} - {""}
                if keys and str(h.get("name") or "").strip():
                    names.append((keys, str(h["name"]).strip()))
    if not names:
        return
    for d, r in zip(devices, results):
        if r["type"] != "wpsd":
            continue
        mine = {_short(d.get("host")), str(r.get("ip") or "")}
        if isinstance(r["data"], dict):
            mine.add(_short(r["data"].get("hostname")))
        mine -= {""}
        for keys, name in names:
            if keys & mine:
                if name != d.get("mon_name"):              # renamed on the monitor since we last looked
                    r["mon_name"] = name
                    if name != r["name"]:
                        r["name"] = r["renamed"] = name
                break


def probe_all(devices: list[dict], beacons: BeaconListener | None) -> list[dict]:
    if not devices:
        return []
    with ThreadPoolExecutor(max_workers=min(12, len(devices))) as ex:
        res = list(ex.map(lambda d: probe(d, beacons), devices))
    _apply_monitor_names(devices, res)
    return res
