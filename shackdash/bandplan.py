"""Australian amateur privileges from the Radiocommunications (Amateur Stations)
Class Licence 2023 (F2023L01648, in force 19 Feb 2024), Schedule 2 tables A-C,
as made. pX = peak envelope power, pY = mean power; 'SSB' in the power column
stands for emission modes J3E/R3E (plus C3F where the table lists it)."""
from __future__ import annotations

SOURCE = ("Radiocommunications (Amateur Stations) Class Licence 2023, Schedule 2 (F2023L01648 as made). "
          "Check legislation.gov.au for later amendments.")

BW8 = "over 8 kHz bandwidth: max 1 W per 100 kHz PSD"
BW8_MAX = "max bandwidth 8 kHz"
BW16 = "over 16 kHz bandwidth: max 1 W per 100 kHz PSD"
BW100 = "max bandwidth 100 kHz"

# (lo kHz, hi kHz, power, limitation)
FOUNDATION = [
    (3500, 3700, "10 W pX", BW8), (7000, 7100, "10 W pX", BW8), (7100, 7300, "10 W pX", BW8_MAX),
    (21000, 21450, "10 W pX", BW8), (28000, 29700, "10 W pX", BW16),
    (144000, 148000, "10 W pX", ""), (430000, 450000, "10 W pX", ""),
]
_STD = "100 W pX SSB, else 30 W pY"
STANDARD = [
    (3500, 3700, _STD, BW8), (7000, 7100, _STD, BW8), (7100, 7300, _STD, BW8_MAX), (14000, 14350, _STD, BW8),
    (21000, 21450, _STD, BW8), (28000, 29700, _STD, BW16),
    (50000, 52000, "100 W pX FM/SSB, else 30 W pY", BW100), (52000, 54000, _STD, ""),
    (144000, 148000, _STD, ""), (430000, 450000, _STD, ""), (1240000, 1300000, _STD, ""),
    (2400000, 2450000, _STD, ""), (5650000, 5850000, _STD, ""),
]
_ADV = "400 W pX FM/SSB, else 120 W pY"
ADVANCED = [
    (135.7, 137.8, "1 W pX EIRP", "max bandwidth 2.1 kHz"), (472, 479, "5 W pX EIRP", "max bandwidth 3 kHz"),
    (1800, 1875, _ADV, BW8), (3500, 3700, _ADV, BW8), (3776, 3800, _ADV, BW8_MAX), (7000, 7100, _ADV, BW8),
    (7100, 7300, _ADV, BW8_MAX), (10100, 10150, _ADV, BW8_MAX), (14000, 14350, _ADV, BW8),
    (18068, 18168, _ADV, BW8), (21000, 21450, _ADV, BW8), (24890, 24990, _ADV, BW8), (28000, 29700, _ADV, BW16),
    (50000, 52000, _ADV, BW100), (52000, 54000, _ADV, ""), (144000, 148000, _ADV, ""), (430000, 450000, _ADV, ""),
    (1240000, 1300000, _ADV, ""), (2300000, 2302000, _ADV, ""), (2400000, 2450000, _ADV, ""),
    (3300000, 3400000, _ADV, ""), (3400000, 3600000, _ADV, "not in the Schedule 3 exclusion areas"),
    (5650000, 5850000, _ADV, ""), (10000000, 10500000, _ADV, ""), (24000000, 24250000, _ADV, ""),
    (47000000, 47200000, _ADV, ""), (76000000, 81000000, _ADV, ""), (122250000, 123000000, _ADV, ""),
    (134000000, 141000000, _ADV, ""), (241000000, 250000000, _ADV, ""),
]
LEVELS = {"Advanced": ADVANCED, "Standard": STANDARD, "Foundation": FOUNDATION}


def band_label(lo_khz: float) -> str:
    names = [(135, "2200m"), (472, "630m"), (1800, "160m"), (3500, "80m"), (7000, "40m"), (10100, "30m"),
             (14000, "20m"), (18068, "17m"), (21000, "15m"), (24890, "12m"), (28000, "10m"), (50000, "6m"),
             (144000, "2m"), (430000, "70cm"), (1240000, "23cm"), (2300000, "13cm"), (3300000, "9cm"),
             (5650000, "6cm"), (10000000, "3cm"), (24000000, "12mm"), (47000000, "6mm"), (76000000, "4mm"),
             (122250000, "2.5mm"), (134000000, "2mm"), (241000000, "1.2mm")]
    lab = ""
    for f, n in names:
        if lo_khz >= f:
            lab = n
    return lab


def fmt_khz(k: float) -> str:
    if k < 1000:
        return f"{k:g} kHz"
    if k < 1_000_000:
        return f"{k / 1000:.3f} MHz"
    return f"{k / 1e6:g} GHz"


def check(khz: float, level: str) -> tuple[bool, str]:
    """(allowed, detail) for a transmit frequency at a qualification level."""
    for lo, hi, pwr, lim in LEVELS.get(level, ADVANCED):
        if lo <= khz <= hi:
            return True, f"{band_label(lo)} {fmt_khz(lo)}–{fmt_khz(hi)} · {pwr}" + (f" · {lim}" if lim else "")
    for other in ("Standard", "Advanced"):
        if other != level and list(LEVELS).index(other) < list(LEVELS).index(level):
            for lo, hi, _p, _l in LEVELS[other]:
                if lo <= khz <= hi:
                    return False, f"outside {level} privileges (needs {other})"
    return False, "not an Australian amateur allocation"
