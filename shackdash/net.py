"""The data hub: every internet source is a Source with a URL, a refresh
interval and a parse function. Fetch + parse run on a thread pool; results
come back to the GUI thread as signals. Raw responses are cached on disk so
the dashboard starts with the last-known data (marked stale) when offline."""
from __future__ import annotations

import gzip
import os
import socket
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from . import config


@dataclass
class Source:
    key: str
    name: str                                   # shown in the SOURCES dialog
    url: str | Callable[[], str]
    interval: int                               # seconds between refreshes
    parse: Callable[[bytes], Any]
    attribution: str = ""
    headers: dict = field(default_factory=dict)
    timeout: int = 45
    max_cache_age: int = 3 * 86400              # older cache files are ignored at start-up
    delay: int = 0                              # hold the first live fetch this many seconds
    fetch: Callable[[], bytes] | None = None    # custom fetch (FTP etc.) instead of an HTTP GET of url
    enabled: Callable[[], bool] | None = None   # False = don't fetch yet (e.g. no callsign set in SETUP)
    # runtime state
    last_ok: float = 0.0
    last_try: float = 0.0
    error: str = ""
    busy: bool = False
    stale: bool = False
    size: int = 0


_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_safe(host, port, family=0, *args, **kwargs):
    """Some home routers answer a name's IPv4 (A) query but time out on its IPv6 (AAAA) query, and then
    Windows fails the whole lookup (getaddrinfo 11004/11001); .local names also wait seconds for an IPv6
    mDNS answer. So .local names go IPv4 first, and any other failure is retried as IPv4-only."""
    if family not in (0, socket.AF_UNSPEC):
        return _getaddrinfo(host, port, family, *args, **kwargs)
    if isinstance(host, str) and host.lower().rstrip(".").endswith(".local"):
        try:
            return _getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
        except socket.gaierror:
            pass
    try:
        return _getaddrinfo(host, port, family, *args, **kwargs)
    except socket.gaierror:
        return _getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)


if not getattr(socket.getaddrinfo, "_ipv4_safe", False):
    _getaddrinfo_ipv4_safe._ipv4_safe = True
    socket.getaddrinfo = _getaddrinfo_ipv4_safe


def http_get(url: str, headers: dict | None = None, timeout: int = 45) -> bytes:
    h = {"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return data


def _deliver(callback, result, err):
    """Hand a finished background job to its page. The page may have been rebuilt meanwhile
    (THEME, SETUP); then its widgets are gone and the result is simply dropped."""
    try:
        callback(result, err)
    except RuntimeError as e:
        if "already deleted" not in str(e):
            raise


class _Signals(QObject):
    done = Signal(str, object, bytes, str)      # key, parsed, raw, error


class _Job(QRunnable):
    def __init__(self, src: Source, url: str, sig: _Signals, raw: bytes | None = None):
        super().__init__()
        self.src, self.url, self.sig, self.raw = src, url, sig, raw

    def run(self):
        try:
            if self.raw is not None:
                raw = self.raw
            elif self.src.fetch is not None:
                raw = self.src.fetch()
            else:
                raw = http_get(self.url, self.src.headers, self.src.timeout)
            result = (self.src.key, self.src.parse(raw), raw if self.raw is None else b"", "")
        except Exception as e:     # noqa: BLE001 - any failure is shown per-source
            if not isinstance(e, (OSError, ValueError)):
                traceback.print_exc()
            result = (self.src.key, None, b"", f"{type(e).__name__}: {e}"[:300])
        try:
            self.sig.done.emit(*result)
        except RuntimeError:        # the window closed while this fetch was still running
            pass


class Hub(QObject):
    updated = Signal(str, object)               # key, parsed data
    status = Signal(str)                        # key (state changed; read hub.sources[key])

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sources: dict[str, Source] = {}
        self.data: dict[str, Any] = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(6)
        self._sig = _Signals()
        self._sig.done.connect(self._done)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._oneshot: dict[str, Callable] = {}
        self._t0 = time.time()
        os.makedirs(config.CACHE_DIR, exist_ok=True)

    def add(self, src: Source) -> None:
        self.sources[src.key] = src

    def start(self) -> None:
        for src in self.sources.values():         # warm start from the disk cache
            path = self._cache_path(src.key)
            try:
                age = time.time() - os.path.getmtime(path)
                if age < src.max_cache_age:
                    with open(path, "rb") as f:
                        raw = f.read()
                    src.stale = True
                    src.last_ok = os.path.getmtime(path)
                    src.busy = True
                    self.pool.start(_Job(src, "", self._sig, raw))
            except OSError:
                pass
        self._t0 = time.time()
        QTimer.singleShot(300, self._tick)
        self._timer.start(5000)

    def refresh(self, key: str) -> None:
        src = self.sources.get(key)
        if src and not src.busy and (src.enabled is None or src.enabled()):
            src.last_try = 0
            self._fetch(src)

    def refresh_all(self) -> None:
        for key in self.sources:
            self.refresh(key)

    def _cache_path(self, key: str) -> str:
        return os.path.join(config.CACHE_DIR, key + ".bin")

    def _tick(self) -> None:
        now = time.time()
        for src in self.sources.values():
            fresh = src.last_ok and not src.stale and now - src.last_ok < src.interval
            # errors retry after 2 min, except a server saying "too many requests" (wait the full interval)
            retry_wait = min(src.interval, 120) if src.error and "429" not in src.error else src.interval
            if now - self._t0 < src.delay or (src.enabled and not src.enabled()):
                continue
            if not src.busy and not fresh and now - src.last_try >= retry_wait:
                self._fetch(src)

    def _fetch(self, src: Source) -> None:
        src.busy = True
        src.last_try = time.time()
        url = "" if src.fetch else src.url() if callable(src.url) else src.url
        self.pool.start(_Job(src, url, self._sig))
        self.status.emit(src.key)

    def _done(self, key: str, parsed, raw: bytes, error: str) -> None:
        src = self.sources[key]
        src.busy = False
        if error:
            src.error = error
        else:
            if raw:                                   # a live fetch (not the start-up cache replay)
                src.error = ""
                src.stale = False
                src.last_ok = time.time()
                src.size = len(raw)
                try:
                    tmp = self._cache_path(key) + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(raw)
                    os.replace(tmp, self._cache_path(key))
                except OSError:
                    pass
            elif key in self.data:                    # cache replay finished after a live result: ignore
                self.status.emit(key)
                return
            self.data[key] = parsed
            self.updated.emit(key, parsed)
        self.status.emit(key)

    # ---- one-off fetches (images on demand etc.) ----------------------------

    def fetch_once(self, url: str, parse: Callable[[bytes], Any], callback: Callable[[Any, str], None],
                   headers: dict | None = None) -> None:
        tag = f"_once{id(callback)}{time.time_ns()}"
        src = Source(tag, tag, url, 0, parse, headers=headers or {})
        sig = _Signals()
        self._oneshot[tag] = sig                         # keep the emitter alive until it fires

        def fin(_key, parsed, _raw, err):
            self._oneshot.pop(tag, None)
            _deliver(callback, parsed, err)
        sig.done.connect(fin)
        self.pool.start(_Job(src, url, sig))

    def run(self, fn: Callable[[], Any], callback: Callable[[Any, str], None]) -> None:
        """Run fn() on the pool; callback(result, error) on the GUI thread."""
        tag = f"_run{time.time_ns()}"
        sig = _Signals()
        self._oneshot[tag] = sig

        def fin(_key, result, _raw, err):
            self._oneshot.pop(tag, None)
            _deliver(callback, result, err)
        sig.done.connect(fin)
        src = Source(tag, tag, "", 0, lambda _raw: fn())
        self.pool.start(_Job(src, "", sig, raw=b""))
