"""ShackDash: internet data for the ham shack, in fifteen tabs (A-O).

    python main.py                  normal start
    python main.py --shots DIR [s]  dev aid: wait s seconds (default 45), save a PNG of every tab, quit
"""
from __future__ import annotations

import ctypes
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from shackdash import config
from shackdash.main_window import DashWindow


def resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def main() -> int:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HamProjects.ShackDash")
    app = QApplication(sys.argv)
    app.setApplicationName("ShackDash")
    app.setApplicationVersion(config.VERSION)
    icon = QIcon(resource("icon.ico")) if os.path.exists(resource("icon.ico")) else None
    if icon:
        app.setWindowIcon(icon)
    cfg = config.load()
    shots = None
    if "--shots" in sys.argv:
        i = sys.argv.index("--shots")
        shots = sys.argv[i + 1]
        delay = float(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 45
        cfg["_nosave"] = True
    win = DashWindow(cfg, icon)
    if shots:
        config.save = lambda _cfg: None            # dev shots never overwrite the real settings
        win.resize(1560, 960)
    win.show()
    if shots:
        from PySide6.QtCore import QTimer
        os.makedirs(shots, exist_ok=True)

        def grab(i=0):
            if i >= len(win.tabs):
                win.close()
                return
            win.show_tab(i)
            QTimer.singleShot(1500, lambda: (win.grab().save(os.path.join(shots, f"tab_{win.tabs[i].title[0]}.png")),
                                             grab(i + 1)))
        QTimer.singleShot(int(delay * 1000), grab)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
