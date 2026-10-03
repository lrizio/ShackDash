"""I · NEWS (RSS headlines)"""
from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QTextBrowser

from ..instruments import fill_table, make_table
from ..sources import NEWS_FEEDS
from ..theme import px
from ..widgets import DeckButton
from .base import Tab, hline_search, key_row, panel, stretch

SHORT = {"news_wia": "WIA", "news_arrl": "ARRL", "news_arnl": "NEWSLINE", "news_dxw": "DX-WORLD"}


class NewsTab(Tab):
    title = "I · NEWS"
    keys = tuple(k for k, _, _ in NEWS_FEEDS)
    footer = "Headlines from WIA, ARRL, Amateur Radio Newsline and DX-World RSS feeds · double-click to open"

    def build(self):
        t = self.t
        self.feed = "ALL"
        self.q = ""
        self.items: list[dict] = []
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(px(12))
        self.tb = make_table(["DATE", "SOURCE", "HEADLINE"], {0: 110, 1: 90}, stretch_col=2)
        self.tb.itemSelectionChanged.connect(self._sel)
        self.tb.doubleClicked.connect(lambda _i: self._open())
        top = QHBoxLayout()
        top.addLayout(key_row(t, ["ALL"] + list(SHORT.values()), self._pick, height=30), 3)
        top.addWidget(hline_search("search headlines", self._search), 1)
        g.addWidget(panel(t, "HEADLINES", [top, self.tb], dot=t.sub), 0, 0)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.head.setStyleSheet(f"font-size:{px(17)}px; font-weight:700;")
        self.meta = QLabel("")
        self.meta.setObjectName("note")
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.open_btn = DeckButton(t, "OPEN IN BROWSER")
        self.open_btn.setFixedHeight(px(40))
        self.open_btn.clicked.connect(self._open)
        g.addWidget(panel(t, "STORY", [self.head, self.meta, stretch(self.body, 1), self.open_btn], dot=t.amber), 0, 1)
        g.setColumnStretch(0, 58)
        g.setColumnStretch(1, 42)
        self._rows: list[dict] = []

    def _pick(self, f):
        self.feed = f
        self._draw()

    def _search(self, s):
        self.q = s.strip().upper()
        self._draw()

    def on_data(self, key, d):
        self._draw()

    def _draw(self):
        items = []
        for key, name, _ in NEWS_FEEDS:
            for it in self.ctx.hub.data.get(key) or []:
                items.append({**it, "src": SHORT[key]})
        items = [i for i in items if (self.feed == "ALL" or i["src"] == self.feed)
                 and (not self.q or self.q in (i["title"] + " " + i["desc"]).upper())]
        items.sort(key=lambda i: -(i["t"] or 0))
        self._rows = items[:400]
        now = time.time()
        fill_table(self.tb, [(time.strftime("%a %d %b", time.localtime(i["t"])) if i["t"] else "", i["src"],
                              i["title"]) for i in self._rows],
                   [self.t.main if i["t"] and now - i["t"] < 86400 else None for i in self._rows])
        if self._rows and not self.head.text():
            self.tb.selectRow(0)

    def _sel(self):
        rows = self.tb.selectionModel().selectedRows()
        if not rows or rows[0].row() >= len(self._rows):
            return
        it = self._rows[rows[0].row()]
        self._cur = it
        self.head.setText(it["title"])
        self.meta.setText(f"{it['src']}  ·  {time.strftime('%A %d %B %Y %H:%M', time.localtime(it['t'])) if it['t'] else ''}")
        body = it["desc"]
        self.body.setPlainText(body[:6000] + ("…" if len(body) > 6000 else ""))

    def _open(self):
        it = getattr(self, "_cur", None)
        if it and it.get("link"):
            QDesktopServices.openUrl(QUrl(it["link"]))
