"""Colour themes and the scaled stylesheet (ported from Rig Deck, the
HamProjects family "3D" look). px() converts design pixels to real pixels
for the current zoom."""
from __future__ import annotations

from dataclasses import dataclass

DESIGN_W, DESIGN_H = 1560, 960

_scale = 1.0


def set_scale(s: float) -> None:
    global _scale
    _scale = max(0.5, min(4.0, s))


def scale() -> float:
    return _scale


def px(n: float) -> int:
    return max(1, round(n * _scale))


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str            # window background
    panel: str         # block / panel fill
    edge: str          # block border
    btn: str           # button fill
    btn_edge: str      # button border
    text: str
    dim: str           # inactive status text
    faint: str         # disabled text
    main: str          # MAIN radio colour
    sub: str           # SUB radio colour
    teal: str          # active-button fill
    teal_edge: str
    amber: str
    purple: str
    red: str
    meter_lo: str
    meter_hi: str
    seg_off: str
    band_ok: str
    screen: str = "#080d10"      # recessed LCD screens
    led_off: str = "#1e2731"     # unlit LED dot




THEMES = [
    # The VK3EI HamProjects family palette (same values as Yaesu Radio Controller /
    # FT991A_Display_Control theme.py: METAL_HI/LO/EDGE, SCREEN, TXT, MUTED, LED_*, BTN_RED).
    Theme("SHACK", bg="#14181d", panel="#14181d", edge="#3a414c", btn="#3a414c",
          btn_edge="#12161b", text="#eef3f8", dim="#a7b3c0", faint="#56606b", main="#57e39a",
          sub="#6cb6ff", teal="#2f6fb0", teal_edge="#6cb6ff", amber="#ffbf5f", purple="#d9a8ff",
          red="#c2402f", meter_lo="#57e39a", meter_hi="#ff7a6b", seg_off="#10202a", band_ok="#6cb6ff",
          screen="#080d10", led_off="#232830"),
    Theme("FLIGHT DECK", bg="#070d13", panel="#0b151e", edge="#1d3140", btn="#0f1c26",
          btn_edge="#27404f", text="#cfdbe3", dim="#6a8290", faint="#34495a", main="#5fe07c",
          sub="#40d2e4", teal="#15505a", teal_edge="#43d6e6", amber="#f0a830", purple="#9b5de5",
          red="#e0413a", meter_lo="#2f8fe8", meter_hi="#b3262a", seg_off="#15293a", band_ok="#2aa1a8"),
    Theme("AMBER NIGHT", bg="#0c0906", panel="#140f0a", edge="#3a2a16", btn="#1a130c",
          btn_edge="#4a3519", text="#f3d9b0", dim="#8f7454", faint="#4a3a28", main="#ffb347",
          sub="#ffd27a", teal="#5a3a12", teal_edge="#ffb347", amber="#ff8c1a", purple="#c46a3a",
          red="#ff4530", meter_lo="#e89a2f", meter_hi="#d4402a", seg_off="#2e2213", band_ok="#c98a2c"),
    Theme("PHOSPHOR", bg="#040b06", panel="#08130b", edge="#1a3a22", btn="#0b1a0f",
          btn_edge="#24502f", text="#b8f5c4", dim="#4f8a5c", faint="#24452c", main="#39ff6a",
          sub="#a6ff4d", teal="#145a26", teal_edge="#39ff6a", amber="#d7ff3a", purple="#3ac9a0",
          red="#ff5a3a", meter_lo="#2fd35a", meter_hi="#e0502a", seg_off="#113019", band_ok="#2fbf5a"),
    Theme("DAYLIGHT", bg="#dfe5ea", panel="#f4f7f9", edge="#aab8c3", btn="#ffffff",
          btn_edge="#9fb0bd", text="#15232d", dim="#6b7c88", faint="#b7c3cc", main="#0f8a3a",
          sub="#0b7fa6", teal="#bfe9ef", teal_edge="#0b7fa6", amber="#d98a00", purple="#7c3fc7",
          red="#d12a22", meter_lo="#1f72c4", meter_hi="#c62828", seg_off="#d3dde4", band_ok="#1c8f98"),
]


def theme_by_name(name: str) -> Theme:
    for t in THEMES:
        if t.name == name:
            return t
    return THEMES[0]


def shade(hex_color: str, amount: int) -> str:
    """Move a colour toward white (+) or black (-) per channel, like the family's _lighten()."""
    h = hex_color.lstrip("#")[-6:]
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    c = lambda v: max(0, min(255, v + amount))
    return f"#{c(r):02x}{c(g):02x}{c(b):02x}"


def _arrow_png(color: str, up: bool) -> str:
    """Spin-box arrow glyph as a PNG in the temp dir (stylesheets can't draw triangles)."""
    import os
    import tempfile
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF
    path = os.path.join(tempfile.gettempdir(), f"shackdash_spin_{color.lstrip('#')}_{'up' if up else 'dn'}.png")
    img = QImage(10, 6, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([QPointF(1, 5), QPointF(9, 5), QPointF(5, 1)] if up else
                            [QPointF(1, 1), QPointF(9, 1), QPointF(5, 5)]))
    p.end()
    img.save(path)
    return path.replace("\\", "/")


def stylesheet(t: Theme) -> str:
    f = px(13)
    r = px(8)
    # Raised metal push-buttons: glossy top, darker bottom edge; they sink when pressed.
    btn = f"""background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {shade(t.btn, 42)},
                    stop:0.45 {shade(t.btn, 14)}, stop:0.5 {t.btn}, stop:1 {shade(t.btn, -14)});
              border: {px(1)}px solid {t.btn_edge}; border-bottom: {px(3)}px solid {shade(t.btn_edge, -8)};
              border-radius: {r}px; color: {t.text}; padding: {px(4)}px {px(12)}px;"""
    return f"""
    QWidget {{ background: {t.bg}; color: {t.text}; font-family: 'Segoe UI', 'Bahnschrift', sans-serif;
               font-size: {f}px; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-size: {px(16)}px; font-weight: 700; letter-spacing: {px(2)}px; }}
    QLabel#dim {{ color: {t.dim}; }}
    QLabel#footer {{ color: {t.dim}; font-size: {px(12)}px; letter-spacing: {px(1)}px; }}
    QPushButton {{ {btn} }}
    QPushButton:hover {{ border-color: {t.teal_edge}; border-bottom-color: {shade(t.btn_edge, -8)}; }}
    QPushButton:pressed {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {shade(t.btn, -30)},
                           stop:1 {shade(t.btn, -6)}); border-bottom-width: {px(1)}px;
                           padding-top: {px(6)}px; }}
    QPushButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {shade(t.teal, 50)},
                           stop:0.45 {shade(t.teal, 18)}, stop:0.5 {t.teal}, stop:1 {shade(t.teal, -18)});
                           border-color: {t.teal_edge}; color: #ffffff; }}
    QDialog, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QListWidget {{ background: {t.bg}; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{ background: {t.screen}; color: {t.teal_edge};
                border: {px(1)}px solid {t.edge}; border-radius: {px(5)}px; padding: 3px; }}
    QSpinBox, QDoubleSpinBox {{ padding-right: {px(22)}px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
                width: {px(20)}px; border-left: 1px solid {t.edge}; background: {t.btn};
                border-top-right-radius: {px(4)}px; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
                width: {px(20)}px; border-left: 1px solid {t.edge}; background: {t.btn};
                border-bottom-right-radius: {px(4)}px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::up-button:hover,
    QDoubleSpinBox::down-button:hover {{ background: {t.teal}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url({_arrow_png(t.text, True)}); width: {px(10)}px; height: {px(6)}px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url({_arrow_png(t.text, False)}); width: {px(10)}px; height: {px(6)}px; }}
    QGroupBox {{ border: 2px solid {t.edge}; border-radius: {px(12)}px; margin-top: 14px; padding-top: 10px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {t.text}; font-weight: 600; }}
    QToolTip {{ background: {t.screen}; color: {t.text}; border: 1px solid {t.teal_edge}; }}
    QMenu {{ background: {t.screen}; border: 1px solid {t.teal_edge}; border-radius: {px(6)}px; }}
    QMenu::item {{ padding: {px(5)}px {px(22)}px; }}
    QMenu::item:selected {{ background: {t.teal}; }}
    QCheckBox {{ spacing: 6px; }}
    QTableWidget, QTreeWidget, QTextBrowser, QListWidget {{ background: {t.screen}; color: {t.text};
                border: {px(1)}px solid {shade(t.edge, -10)}; border-radius: {px(8)}px;
                gridline-color: {shade(t.screen, 18)}; selection-background-color: {t.teal};
                selection-color: #ffffff; alternate-background-color: {shade(t.screen, 7)};
                font-size: {px(12.5)}px; }}
    QTableWidget::item {{ padding: 0 {px(4)}px; }}
    QHeaderView::section {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {shade(t.btn, 30)},
                stop:0.5 {t.btn}, stop:1 {shade(t.btn, -12)}); color: {t.dim}; font-weight: 700;
                font-size: {px(11.5)}px; letter-spacing: 1px; border: none;
                border-right: 1px solid {shade(t.btn, -25)}; border-bottom: {px(2)}px solid {shade(t.btn, -35)};
                padding: {px(3)}px {px(5)}px; }}
    QTableCornerButton::section {{ background: {t.btn}; border: none; }}
    QScrollBar:vertical {{ background: {t.screen}; width: {px(12)}px; margin: 0; border: none; }}
    QScrollBar:horizontal {{ background: {t.screen}; height: {px(12)}px; margin: 0; border: none; }}
    QScrollBar::handle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {shade(t.btn, 30)},
                stop:1 {shade(t.btn, -10)}); border-radius: {px(5)}px; min-height: {px(24)}px; min-width: {px(24)}px;
                border: 1px solid {shade(t.btn, -30)}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QSlider::groove:horizontal {{ background: {t.screen}; height: {px(8)}px; border-radius: {px(4)}px;
                border: 1px solid {t.edge}; }}
    QSlider::handle:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {shade(t.btn, 50)},
                stop:1 {shade(t.btn, -10)}); width: {px(20)}px; margin: -{px(7)}px 0; border-radius: {px(6)}px;
                border: 1px solid {t.teal_edge}; }}
    QLabel#caption {{ color: {t.dim}; font-size: {px(11.5)}px; font-weight: 700; letter-spacing: 1px; }}
    QLabel#note {{ color: {t.dim}; font-size: {px(11.5)}px; }}
    QLabel#big {{ font-family: 'Bahnschrift'; font-weight: 600; }}
    """
