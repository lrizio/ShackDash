# ShackDash

A Windows desktop dashboard of internet data that is useful in the ham shack. It uses the HamProjects
family 3D look (SHACK theme, ported from Rig Deck), and has fifteen tabs (O is optional):

| Tab | What's on it | Sources (all free, no key) |
|---|---|---|
| **A · Space WX** | SFI, sunspots, A, Kp, X-ray class, solar wind, Bz, protons, NOAA R/S/G, nearest MUF; N0NBH band conditions; Kp 3-day observed+forecast; X-ray, solar wind, IMF and proton plots; nearest ionosondes (MUFd/foF2); SWPC alerts; OVATION aurora australis | NOAA SWPC, hamqsl.com (N0NBH), prop.kc2g.com |
| **B · Live** | DX cluster (band filter, skimmer toggle, active-DXpedition highlight); who hears me (RBN CW+FT8, PSKReporter, WSPR) with map; band x continent activity for my grid field; NCDXF beacons on air now | telnet cluster, RBN telnet, PSKReporter, wspr.live |
| **C · Local** | UTC/local clocks, sunrise/set/twilight, sun and moon position, moon phase, moonrise/set, EME distance loss, grey-line map, short/long-path beam headings (call/prefix/grid/click), bearings to DX areas | computed locally (cty.dat for prefixes) |
| **D · Sats** | 24 h pass list for ~95 amateur satellites, live tracker with Doppler-corrected RX/TX frequencies, sky plot, ISS + selected ground track and footprint, SatNOGS latest observations | CelesTrak TLEs + SGP4, SatNOGS DB/Network |
| **E · DX & Contests** | contests on now / next 8 days, NG3K announced DX operations (flags ones spotted on the cluster), Club Log DXCC most wanted | WA7BNM, NG3K, Club Log |
| **F · Digital** | XLX reflectors (last heard), BrandMeister talkgroup directory, YSF reflector list | xlxapi.rlx.lu, BrandMeister API, Pi-Star host files |
| **G · VHF/UHF** | Hepburn tropo ducting forecast (animated, valid times), VHF+ cluster spots and path map, N0NBH VHF outlook | dxinfocentre.com, cluster |
| **H · Weather** | current conditions, antenna wind alert (threshold in SETUP), thunderstorm risk (forecast weather codes + CAPE), 48 h wind/temperature/CAPE plots, 3-day outlook, BoM rain radar loop, BoM state warnings | Open-Meteo, BoM (anonymous FTP + RSS) |
| **I · News** | WIA, ARRL, Amateur Radio Newsline and DX-World headlines with the story text | RSS |
| **J · Sun** | NOAA 27-day outlook (flux, A, Kp), solar cycle observed + predicted, D-RAP absorption map, SDO/LASCO images | NOAA SWPC, NASA SDO, SOHO |
| **K · Portable** | POTA / WWFF / ParksnPeaks activators merged, program/region/band filters, map, beam + privilege check | api.pota.app, spots.wwff.co, parksnpeaks.org |
| **L · APRS** | APRS-IS stations, objects and weather around the QTH (receive-only login, range filter), tracks, packet log | APRS-IS (aprs2.net) |
| **M · Planner** | meteor showers (radiant elevation at QTH), 4-week EME planner, ARISS school contacts with ISS-in-range check, ARISS SSTV events | computed locally, ariss.org |
| **N · Tools** | callsign lookup (cty, LoTW, callook.info for US), KiwiSDR receivers near me / near the DX, AU licence privileges + frequency checker | cty, LoTW CSV, callook.info, kiwisdr list, Class Licence 2023 |
| **O · My Shack** | own LAN gear: WPSD / Pi-Star hotspots (m5status.php, installer in `hotspot/`), HF Matrix boxes (/api/status + UDP beacon 51500), ping/web devices; editable list; hide it in SETUP | the LAN |

The **SOURCES** button (or click the DATA lamp) lists every source with its state, age, interval and credit, plus
the items deferred for later: BoM space weather (needs a key), aprs.fi (key), QRZ/HamQTH (account), SOTAwatch
(its API terms need prior approval, so SOTA arrives via ParksnPeaks), VK callsign holders (not in the ACMA register
since the 2024 class licence), Blitzortung (licence), BrandMeister last-heard (socket.io stream), AMSAT status (API
returned nothing).

## User guide

`ShackDash User Guide.pdf` (in the release zip) explains every control and every panel. Regenerate it with `python build_user_guide.py`;
the screenshots come from `python scripts/guide_screens.py`, which runs the live app and saves them to `docs/guide/`
(set `QT_QPA_PLATFORM=offscreen` and `QT_QPA_FONTDIR=C:/Windows/Fonts` to do it without a window appearing).

## Running

* `ShackDash.exe` from the release zip
* From source: `python main.py` (`pip install -r requirements.txt`)
* **SETUP**: callsign, grid locator (QTH), cluster host:port, RBN on/off, wind alert, satellite min elevation, size,
  licence level, BoM state + radar ID, APRS on/off + radius, show/hide the MY SHACK tab, start-up check for a newer release on/off
* Keys: `1`-`9`, `0` pick tabs A-J, `Ctrl+Tab` / `Ctrl+Shift+Tab` step through all, `Ctrl+R` refresh all, `F11` full
  screen; double-click the title bar to maximise

Settings are in `%APPDATA%\ShackDash\config.json`. The last good copy of every source is cached in
`%APPDATA%\ShackDash\cache`, so the dashboard opens with data (marked cached) even offline.

## Developing

* `python main.py --shots DIR [seconds]` waits (default 45 s), saves a PNG of every tab to DIR, and quits
* Icon: `python scripts/make_icon.py`
* Exe:

```
python -m PyInstaller --noconfirm --onefile --windowed --name ShackDash --icon "%CD%\icon.ico" --add-data "%CD%\icon.ico;." --distpath build --workpath %TEMP%\sd_build --specpath %TEMP%\sd_build main.py
```

Layout: `shackdash/net.py` (fetch hub + disk cache), `sources.py` + `extra_sources.py` (every source + parser),
`feeds.py` (telnet cluster/RBN), `aprs.py` (APRS-IS feed + decoder), `myshack.py` (LAN device probes),
`bandplan.py` (AU class licence tables), `astro.py`, `sats.py`, `geo.py` (grids, great circles, cty), `mapview.py`, `instruments.py`,
`widgets.py`/`theme.py` (family look), `tabs/` (one module per tab), `main_window.py`.

## Licence and disclaimer

ShackDash is free software under the [MIT License](LICENSE). It is provided **as is, without warranty of any kind**,
and you use it at your own risk. Weather, warnings, propagation and licence-privilege information is for hobby
interest only. **Do not rely on it for safety or regulatory decisions.** Please read the full [DISCLAIMER](DISCLAIMER.md).

ShackDash is not affiliated with or endorsed by any of the organisations whose data it displays. All trademarks
belong to their owners. Data is © its respective providers; see the SOURCES button in the program for credits.

73 de VK3EI