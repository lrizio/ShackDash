"""Start-up check for a newer public release. One small GET of the GitHub 'latest release' record,
on a background thread; nothing is downloaded or installed and nothing but the request itself is sent."""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import config
from .net import http_get

REPO = "lrizio/ShackDash"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE_URL = f"https://github.com/{REPO}/releases/latest"


def _ver(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text)[:4])


def newer(latest: str, current: str = config.VERSION) -> bool:
    try:
        return _ver(latest) > _ver(current)
    except ValueError:
        return False


def parse(raw: bytes) -> tuple[str, str] | None:
    """(version, page URL) of the latest release if it is newer than this program, else None."""
    rec = json.loads(raw)
    tag = str(rec.get("tag_name", ""))
    if rec.get("draft") or rec.get("prerelease") or not newer(tag):
        return None
    return tag.lstrip("vV"), str(rec.get("html_url") or PAGE_URL)


class _Result(QObject):
    done = Signal(object)                       # (version, url) or None


class _Job(QRunnable):
    def __init__(self, res: _Result):
        super().__init__()
        self.res = res

    def run(self):
        try:
            out = parse(http_get(API_URL, {"Accept": "application/vnd.github+json"}, timeout=15))
        except Exception:                       # noqa: BLE001 - offline, rate limited, odd reply: stay silent
            out = None
        try:
            self.res.done.emit(out)
        except RuntimeError:                    # window closed while the check was running
            pass


class UpdateChecker(QObject):
    found = Signal(str, str)                    # version, release page URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self._res = _Result()
        self._res.done.connect(lambda r: r and self.found.emit(*r))
        self._pool = QThreadPool(self)

    def start(self) -> None:
        self._pool.start(_Job(self._res))
