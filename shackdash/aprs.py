"""APRS-IS, receive only: a read-only login (passcode -1) with a range filter
around the QTH, and a decoder for the packet types that carry a position
(uncompressed, compressed, Mic-E, objects, items), plus messages, status
and weather."""
from __future__ import annotations

import re
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import config

SYMBOLS = {  # primary-table symbol code -> what it is ('\\' table falls back to the same meaning)
    "-": "home", ">": "car", "k": "truck", "u": "truck", "v": "van", "j": "jeep", "R": "RV", "<": "motorbike",
    "b": "bicycle", "[": "walker", "_": "weather", "#": "digipeater", "&": "gateway", "r": "repeater",
    "y": "home (yagi)", "O": "balloon", "^": "aircraft", "'": "aircraft", "s": "boat", "Y": "yacht",
    "a": "ambulance", "f": "fire truck", "p": "rover", "n": "node", "`": "dish", "l": "laptop", "$": "phone",
    "I": "TCP/IP", "=": "train", "U": "bus", "X": "helicopter", "!": "police", "+": "Red Cross",
    ";": "portable", "h": "hospital", "o": "EOC", "E": "eyeball", "W": "NWS", "x": "X-APRS", "m": "Mic-E rptr",
}
DIGI_SYMS = {"#", "&", "r", "n"}


def symbol_name(table: str, code: str) -> str:
    if table == "\\" and code == "#":
        return "digipeater (wide)"
    if table and table not in "/\\" and code in "#&":
        return ("digipeater" if code == "#" else "gateway") + f" ({table})"
    return SYMBOLS.get(code, "station")


def _uncompressed(s: str):
    m = re.match(r"(\d{2})([\d ]{2}\.[\d ]{2})([NS])(.)(\d{3})([\d ]{2}\.[\d ]{2})([EW])(.)", s)
    if not m:
        return None
    lat = int(m.group(1)) + float(m.group(2).replace(" ", "0")) / 60
    lon = int(m.group(5)) + float(m.group(6).replace(" ", "0")) / 60
    if m.group(3) == "S":
        lat = -lat
    if m.group(7) == "W":
        lon = -lon
    return lat, lon, m.group(4), m.group(8), s[19:]


def _b91(s: str) -> int:
    v = 0
    for ch in s:
        v = v * 91 + ord(ch) - 33
    return v


def _compressed(s: str):
    if len(s) < 13 or not re.match(r"[/\\A-Za-j]", s[0]):
        return None
    try:
        lat = 90 - _b91(s[1:5]) / 380926
        lon = -180 + _b91(s[5:9]) / 190463
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    out = [lat, lon, s[0], s[9], s[13:]]          # a letter in the table slot is an overlay
    if s[10] != " " and ord(s[12]) - 33 & 0x18 != 0x10 and "!" <= s[10] <= "z":
        out.append(((ord(s[10]) - 33) * 4, round(1.08 ** (ord(s[11]) - 33) - 1)))     # course, speed kt
    return out


def _mic_e(dst: str, info: str):
    """Mic-E (Kenwood/Yaesu handhelds and mobiles): latitude lives in the destination call."""
    d = dst.split("-")[0]
    if len(d) != 6 or len(info) < 9:
        return None
    digits = ""
    for ch in d:
        if ch.isdigit():
            digits += ch
        elif "A" <= ch <= "J":
            digits += str(ord(ch) - 65)
        elif "P" <= ch <= "Y":
            digits += str(ord(ch) - 80)
        elif ch in "KLZ":
            digits += "0"
        else:
            return None
    lat = int(digits[0:2]) + float(digits[2:4] + "." + digits[4:6]) / 60
    if not ("P" <= d[3] <= "Z"):
        lat = -lat
    lon_off = 100 if "P" <= d[4] <= "Z" else 0
    west = "P" <= d[5] <= "Z"
    b = [ord(c) - 28 for c in info[1:7]]
    deg = b[0] + lon_off
    if 180 <= deg <= 189:
        deg -= 80
    elif 190 <= deg <= 199:
        deg -= 190
    mins = b[1] - 60 if b[1] >= 60 else b[1]
    lon = deg + (mins + b[2] / 100) / 60
    if west:
        lon = -lon
    sp = b[3] * 10 + b[4] // 10
    course = (b[4] % 10) * 100 + b[5]
    if sp >= 800:
        sp -= 800
    if course >= 400:
        course -= 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    comment = info[9:]
    comment = re.sub(r"^[`'>\]]", "", comment)
    m = re.search(r"([!-{]{3})\}", comment)                # altitude: 3 base-91 chars + '}', metres - 10000
    alt = ""
    if m:
        alt = f"/A={round((_b91(m.group(1)) - 10000) / 0.3048):06d}"
        comment = comment[:m.start()] + comment[m.end():]
    comment = re.sub(r"(_[\d\"%)(]|[=^])$", "", comment)    # Yaesu / Kenwood radio-type suffix
    return lat, lon, info[8], info[7], alt + comment, (course, sp)


def parse(line: str) -> dict | None:
    if not line or line.startswith("#") or ":" not in line or ">" not in line:
        return None
    head, info = line.split(":", 1)
    src, _, rest = head.partition(">")
    dst, *path = rest.split(",")
    p = {"src": src, "dst": dst, "path": ",".join(path), "raw": line, "t": time.time(), "kind": "other"}
    if not info:
        return p
    c = info[0]
    pos = None
    if c in "!=":
        pos = _uncompressed(info[1:]) or _compressed(info[1:])
        p["kind"] = "position"
    elif c in "/@":
        pos = _uncompressed(info[8:]) or _compressed(info[8:])
        p["kind"] = "position"
    elif c == ";" and len(info) > 18:
        p["obj"] = info[1:10].strip()
        p["alive"] = info[10] == "*"
        pos = _uncompressed(info[18:]) or _compressed(info[18:])
        p["kind"] = "object"
    elif c == ")":
        m = re.match(r"\)([^!_]{3,9})([!_])(.*)", info)
        if m:
            p["obj"], p["alive"] = m.group(1).strip(), m.group(2) == "!"
            pos = _uncompressed(m.group(3)) or _compressed(m.group(3))
            p["kind"] = "object"
    elif c in "`'":
        pos = _mic_e(dst, info)
        p["kind"] = "position"
    elif c == ":" and len(info) > 11 and info[10] == ":":
        p["kind"] = "message"
        p["to"] = info[1:10].strip()
        p["text"] = re.sub(r"\{\w*$", "", info[11:]).strip()
    elif c == ">":
        p["kind"] = "status"
        p["comment"] = info[1:].strip()
    elif c == "_":
        p["kind"] = "weather"
        p["comment"] = info[9:]
    elif c == "T":
        p["kind"] = "telemetry"
    if pos:
        lat, lon, table, code, comment, *mv = pos
        p.update(lat=lat, lon=lon, table=table, sym=code, comment=comment.strip()[:120],
                 what=symbol_name(table, code))
        if mv:
            p["course"], p["speed_kt"] = mv[0]
        elif code != "_":
            m = re.match(r"(\d{3})/(\d{3})", comment)
            if m:
                p["course"], p["speed_kt"] = int(m.group(1)), int(m.group(2))
                p["comment"] = comment[7:].strip()[:120]
        m = re.search(r"/A=(-?\d{5,6})", p["comment"])
        if m:
            p["alt_ft"] = int(m.group(1))
            p["comment"] = (p["comment"][:m.start()] + p["comment"][m.end():]).strip()
        if code == "_":
            p["kind"] = "weather"
    if p.get("kind") == "weather":
        txt = p.get("comment", "")
        m = re.search(r"t(-?\d{2,3})", txt)
        if m:
            p["temp_c"] = (int(m.group(1)) - 32) * 5 / 9
        m = re.search(r"^(\d{3}|\.{3})/(\d{3}|\.{3})", txt)
        if m and m.group(2).isdigit():
            p["wind_kmh"] = int(m.group(2)) * 1.609
    return p


class AprsFeed(QObject):
    packet = Signal(dict)
    state = Signal(str, bool)

    def __init__(self, call: str, lat: float, lon: float, km: int, host: str = "rotate.aprs2.net", port: int = 14580):
        super().__init__()
        self.call = re.sub(r"[^A-Z0-9-]", "", call.upper()) or "N0CALL"
        self.lat, self.lon, self.km = lat, lon, km
        self.host, self.port = host, port
        self.lines = 0
        self.connected = False
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="feed-APRS")

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass

    def _run(self):
        backoff = 5
        while not self._stop.is_set():
            try:
                self.state.emit(f"connecting to {self.host}:{self.port}", False)
                s = socket.create_connection((self.host, self.port), timeout=20)
                self._sock = s
                s.settimeout(120)                    # the server sends a keepalive comment every ~20 s
                login = (f"user {self.call} pass -1 vers ShackDash {config.VERSION} "
                         f"filter r/{self.lat:.2f}/{self.lon:.2f}/{self.km}\r\n")
                s.sendall(login.encode())
                self.connected = True
                self.state.emit(f"connected to {self.host} (receive only, {self.km} km)", True)
                backoff = 5
                buf = b""
                while not self._stop.is_set():
                    chunk = s.recv(8192)
                    if not chunk:
                        raise ConnectionError("closed by server")
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        self.lines += 1
                        try:
                            p = parse(raw.decode("utf-8", "replace").strip("\r"))
                        except (ValueError, IndexError):
                            p = None
                        if p:
                            self.packet.emit(p)
            except (OSError, ConnectionError) as e:
                self.connected = False
                if self._stop.is_set():
                    break
                self.state.emit(f"offline ({type(e).__name__}); retry in {backoff}s", False)
            finally:
                try:
                    if self._sock:
                        self._sock.close()
                except OSError:
                    pass
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 300)
