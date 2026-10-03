"""Streaming telnet feeds: a DX cluster and the Reverse Beacon Network.
Each runs in its own thread, logs in with the callsign, reconnects with
back-off, and emits parsed spots to the GUI thread."""
from __future__ import annotations

import re
import socket
import threading
import time

from PySide6.QtCore import QObject, Signal

SPOT_RE = re.compile(r"^DX de\s+([A-Z0-9/#\-]+)[:\s]+\s*(\d+\.\d+)\s+([A-Z0-9/]+)\s+(.*?)\s*(\d{4})Z", re.I)

BANDS = [  # (name, lo kHz, hi kHz)
    ("160m", 1800, 2000), ("80m", 3500, 4000), ("60m", 5250, 5450), ("40m", 7000, 7300), ("30m", 10100, 10150),
    ("20m", 14000, 14350), ("17m", 18068, 18168), ("15m", 21000, 21450), ("12m", 24890, 24990),
    ("10m", 28000, 29700), ("6m", 50000, 54000), ("4m", 70000, 71000), ("2m", 144000, 148000),
    ("70cm", 420000, 450000), ("23cm", 1240000, 1300000)]
HF_BANDS = [b[0] for b in BANDS[:10]]


def band_of(khz: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= khz <= hi:
            return name
    return ""


def mode_guess(khz: float, comment: str) -> str:
    c = comment.upper()
    for m in ("FT8", "FT4", "RTTY", "PSK31", "PSK", "JT65", "MSK144", "Q65", "SSTV", "CW", "SSB", "USB", "LSB",
              "FM", "AM", "JS8", "WSPR"):
        if re.search(rf"\b{m}\b", c):
            return {"USB": "SSB", "LSB": "SSB", "PSK31": "PSK"}.get(m, m)
    # FT8 dial frequencies
    for f in (1840, 3573, 5357, 7074, 10136, 14074, 18100, 21074, 24915, 28074, 50313, 144174):
        if f <= khz <= f + 3:
            return "FT8"
    sub = {1800: 1840, 3500: 3600, 7000: 7040, 10100: 10150, 14000: 14100, 18068: 18110, 21000: 21150,
           24890: 24930, 28000: 28300, 50000: 50100}
    for lo, cw_top in sub.items():
        if lo <= khz < cw_top:
            return "CW"
    return "SSB" if band_of(khz) in HF_BANDS else ""


class TelnetFeed(QObject):
    spot = Signal(dict)
    state = Signal(str, bool)          # message, connected

    def __init__(self, host: str, port: int, call: str, name: str, filter_call: str | None = None,
                 login_cmds: tuple[str, ...] = ()):
        super().__init__()
        self.host, self.port, self.call, self.name = host, port, call, name
        self.filter_call = filter_call.upper() if filter_call else None
        self.login_cmds = login_cmds
        self.lines = 0
        self.connected = False
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"feed-{name}")

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
                s.settimeout(300)
                buf = b""
                logged_in = False
                t_conn = time.time()
                while not self._stop.is_set():
                    chunk = s.recv(8192)
                    if not chunk:
                        raise ConnectionError("closed by server")
                    buf += chunk
                    low = buf.lower()
                    if not logged_in and (b"call" in low or b"login" in low) and (
                            buf.rstrip().endswith((b":", b">")) or time.time() - t_conn > 4):
                        s.sendall(self.call.encode() + b"\r\n")
                        for cmd in self.login_cmds:
                            time.sleep(0.4)
                            s.sendall(cmd.encode() + b"\r\n")
                        logged_in = True
                        self.connected = True
                        backoff = 5
                        self.state.emit(f"connected to {self.host}", True)
                    *lines, buf = buf.split(b"\n")
                    for raw in lines:
                        self._line(raw.decode("latin-1", "replace").strip("\r\x07 "))
                    if len(buf) > 65536:
                        buf = b""
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

    def _line(self, line: str):
        self.lines += 1
        if not line.startswith("DX de"):
            return
        if self.filter_call and f" {self.filter_call} " not in line.upper() + " ":
            return
        m = SPOT_RE.match(line)
        if not m:
            return
        spotter, freq, dx, comment, hhmm = m.groups()
        dx = dx.upper()
        if self.filter_call and dx != self.filter_call:
            return
        khz = float(freq)
        now = time.gmtime()
        t = time.time()
        sp = {"spotter": spotter.rstrip(":").upper(), "khz": khz, "dx": dx, "comment": comment.strip(),
              "time": hhmm, "t": t, "band": band_of(khz), "mode": mode_guess(khz, comment), "src": self.name}
        if self.name.startswith("RBN"):
            # "CW    23 dB  25 WPM  CQ"
            rm = re.match(r"(\S+)\s+(-?\d+)\s*dB(?:\s+(\d+)\s*(WPM|BPS))?\s*(.*)", comment)
            if rm:
                sp["mode"], sp["snr"], sp["wpm"] = rm.group(1), int(rm.group(2)), rm.group(3) or ""
            sp["spotter"] = sp["spotter"].replace("-#", "")
        self.spot.emit(sp)
