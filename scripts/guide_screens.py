"""Screenshots for the User Guide, taken from the live app (real data) into docs/guide/.

    python scripts/guide_screens.py [wait_seconds]

Set QT_QPA_PLATFORM=offscreen to take them without a window appearing on the desktop.

Runs the dashboard at 1560x960 with the saved settings (never saving them), waits for
the data to arrive, sets up a few illustrative states, then grabs each tab, the top bar,
the tab keys and both dialogs.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QRect, QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shackdash import config  # noqa: E402
from shackdash.main_window import DashWindow, SetupDialog, SourcesDialog  # noqa: E402

OUT = os.path.join(ROOT, "docs", "guide")


def main():
    wait = float(sys.argv[1]) if len(sys.argv) > 1 else 70
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    cfg = config.load()
    config.save = lambda _cfg: None
    win = DashWindow(cfg, QIcon(os.path.join(ROOT, "icon.ico")))
    win.resize(1560, 960)
    win.show()

    def save(widget, name, rect: QRect | None = None):
        pm = widget.grab(rect) if rect else widget.grab()
        pm.save(os.path.join(OUT, name))
        print("saved", name)

    steps = []

    def tab(i, name, prep=None):
        def go():
            win.show_tab(i)
            if prep:
                prep()
        steps.append((go, 0))
        steps.append((lambda: save(win, name), 1800))

    tab(0, "tab_a.png")
    tab(1, "tab_b.png")
    tab(2, "tab_c.png", lambda: win.tabs[2].target.setText("W1AW"))
    tab(3, "tab_d.png")
    tab(4, "tab_e.png")
    tab(5, "tab_f.png")
    tab(6, "tab_g.png")
    tab(7, "tab_h.png")
    tab(8, "tab_i.png")
    tab(9, "tab_j.png")
    tab(10, "tab_k.png")
    tab(11, "tab_l.png")
    tab(12, "tab_m.png")

    def lookup():
        tools = win.tabs[13]
        tools.call_in.setText("W1AW")
        tools._lookup()
        tools.freq_in.setText("14.074")
    steps.append((lambda: (win.show_tab(13), lookup()), 0))
    steps.append((lambda: save(win, "tab_n.png"), 5000))            # callook.info answers in a second or two
    tab(14, "tab_o.png")

    def chrome():
        bar_h = win.stack.geometry().top()
        save(win, "topbar.png", QRect(0, 0, win.width(), bar_h))
    steps.append((chrome, 300))

    def dialogs():
        sd = SourcesDialog(win)
        sd.refresh()
        sd.show()
        QTimer.singleShot(800, lambda: (save(sd, "sources.png"), sd.close()))
        su = SetupDialog(win)
        su.show()
        QTimer.singleShot(900, lambda: (save(su, "setup.png"), su.close()))
    steps.append((dialogs, 300))
    steps.append((win.close, 2500))

    def run(k=0):
        if k >= len(steps):
            return
        fn, delay = steps[k]
        QTimer.singleShot(delay, lambda: (fn(), run(k + 1)))
    QTimer.singleShot(int(wait * 1000), run)
    app.exec()


if __name__ == "__main__":
    main()
