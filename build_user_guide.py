#!/usr/bin/env python3
"""Generates build/ShackDash User Guide.pdf -- the end-user guide for ShackDash.

Same structure and styling as the other HamProjects guides (Rig Deck, Yaesu Radio
Controller). Screenshots come from docs/guide/, taken from the live app by
scripts/guide_screens.py.

Usage (from this project's root):
    python scripts/guide_screens.py      (optional: refresh the screenshots)
    python build_user_guide.py

Requires: pip install reportlab pillow (build-time only).
"""
from __future__ import annotations

import os
import sys

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, ListFlowable, ListItem, PageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(ROOT, "build", "ShackDash User Guide.pdf")
SHOTS = os.path.join(ROOT, "docs", "guide")
sys.path.insert(0, ROOT)
from shackdash import __version__ as VERSION  # noqa: E402

ACCENT = colors.HexColor("#1565c0")
CALLOUT_BG = colors.HexColor("#fff3e0")
CALLOUT_BORDER = colors.HexColor("#e0a030")
NOTE_BG = colors.HexColor("#e8f0fe")
NOTE_BORDER = colors.HexColor("#8ab4f8")
TABLE_HEADER_BG = colors.HexColor("#eeeeee")
MUTED = colors.HexColor("#555555")
CONTENT_W = 7.2 * inch

styles = getSampleStyleSheet()
style_title = ParagraphStyle("GuideTitle", parent=styles["Title"], fontSize=26, leading=30, spaceAfter=2)
style_subtitle = ParagraphStyle("GuideSubtitle", parent=styles["Normal"], fontSize=11, leading=14,
                                textColor=MUTED, alignment=TA_CENTER, spaceAfter=14)
style_body = ParagraphStyle("GuideBody", parent=styles["Normal"], fontSize=10, leading=13, spaceAfter=5)
style_h2 = ParagraphStyle("GuideH2", parent=styles["Heading2"], fontSize=12.5, leading=14, textColor=ACCENT,
                          spaceBefore=8, spaceAfter=3)
style_h3 = ParagraphStyle("GuideH3", parent=styles["Heading3"], fontSize=10.5, leading=13,
                          textColor=colors.HexColor("#333333"), spaceBefore=5, spaceAfter=2)
style_bullet = ParagraphStyle("GuideBullet", parent=styles["Normal"], fontSize=9.5, leading=12)
style_note = ParagraphStyle("GuideNote", parent=styles["Normal"], fontSize=9.5, leading=13)
style_cell = ParagraphStyle("GuideCell", parent=styles["Normal"], fontSize=9, leading=11.5)
style_head = ParagraphStyle("GuideHead", parent=style_cell, fontName="Helvetica-Bold")
style_caption = ParagraphStyle("GuideCaption", parent=styles["Normal"], fontSize=8.5, leading=11,
                               textColor=MUTED, alignment=TA_CENTER, spaceBefore=2, spaceAfter=8)


def P(text, style=style_body):
    return Paragraph(text, style)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, style_bullet), spaceAfter=2.5) for i in items],
                        bulletType="bullet", bulletFontSize=7, leftIndent=14, bulletOffsetY=1)


def numbered(items):
    return ListFlowable([ListItem(Paragraph(i, style_bullet), spaceAfter=4) for i in items],
                        bulletType="1", leftIndent=18)


def box(text, bg=NOTE_BG, border=NOTE_BORDER):
    return Table([[Paragraph(text, style_note)]], colWidths=[CONTENT_W],
                 style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 1, border),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                                   ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))


def warn(text):
    return box(text, CALLOUT_BG, CALLOUT_BORDER)


def table(rows, widths):
    data = [[Paragraph(c, style_head) for c in rows[0]]] + \
           [[Paragraph(c, style_cell) for c in r] for r in rows[1:]]
    return Table(data, colWidths=[w * inch for w in widths], repeatRows=1,
                 style=TableStyle([("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
                                   ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                   ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))


def img(name, width):
    path = os.path.join(SHOTS, name)
    w, h = PILImage.open(path).size
    return Image(path, width=width, height=width * h / w)


def shot(name, width=CONTENT_W, caption=None):
    parts = [img(name, width)]
    if caption:
        parts.append(Paragraph(caption, style_caption))
    return KeepTogether(parts)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.65 * inch, 0.3 * inch, f"ShackDash v{VERSION} - User Guide")
    canvas.drawRightString(LETTER[0] - 0.65 * inch, 0.3 * inch, f"Page {doc.page}")
    canvas.restoreState()


PANEL_W = [1.65, 5.55]


def tab_section(f, title, shot_name, caption, intro, panels, extra=None, width=CONTENT_W):
    f.append(PageBreak())
    f.append(P(title, style_h2))
    f.append(P(intro))
    f.append(shot(shot_name, width, caption=caption))
    f.append(table([["Panel", "What it shows and how to read it"]] + panels, PANEL_W))
    for e in extra or []:
        f.append(Spacer(1, 6))
        f.append(e)


def build():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    doc = SimpleDocTemplate(OUT_PATH, pagesize=LETTER, title="ShackDash - User Guide",
                            author="ShackDash", topMargin=0.45 * inch, bottomMargin=0.55 * inch,
                            leftMargin=0.65 * inch, rightMargin=0.65 * inch)
    f = []
    f.append(P(f"ShackDash v{VERSION}", style_title))
    f.append(P("User Guide | Internet data for the ham shack, on one Windows screen", style_subtitle))
    f.append(Table([[""]], colWidths=[CONTENT_W], rowHeights=[1],
                   style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1, colors.HexColor("#cccccc"))])))
    f.append(Spacer(1, 8))
    f.append(P(
        "ShackDash gathers the internet data a radio amateur checks before and while operating, "
        "and shows it in fifteen tabs: space weather and HF propagation, live band activity, local sun "
        "and moon, satellites, DX and contests, digital-voice networks, VHF/UHF propagation, weather, "
        "news, the sun and the month ahead, portable activators, local APRS, a planner, station tools "
        "and, optionally, your own shack's LAN gear. Everything comes from free public sources (no accounts or keys). It refreshes itself in "
        "the background, so you can leave it running on a second monitor."))
    f.append(shot("tab_a.png", caption="Tab A, Space Weather. The top bar and the row of tab keys are "
                                       "the same on every tab."))

    # ------------------------------------------------------------------------------------------------
    f.append(P("Starting ShackDash", style_h2))
    f.append(bullets([
        "Double-click the <b>ShackDash</b> icon on the Desktop (it runs "
        "<b>build\\ShackDash.exe</b>). Nothing else needs installing.",
        "The PC needs an internet connection. Each panel fills in as its source replies. Most take a "
        "few seconds; PSKReporter can take up to a minute.",
        "If you start it offline, it shows the last data it saved (marked <i>cached</i> in the SOURCES "
        "list) and catches up once the connection is back.",
    ]))
    f.append(P("First-Time Setup", style_h2))
    f.append(P("SETUP opens by itself the first time ShackDash starts (and any time from <b>SETUP</b> in the top "
               "bar). Fill in your station details and click <b>SAVE</b>. A new installation starts with no "
               "callsign: nothing that uses it (DX cluster, RBN, APRS-IS, PSKReporter, WSPR) connects until you "
               "enter one, and until you save a grid locator the top bar reminds you with "
               "<i>set your QTH in SETUP</i>."))
    f.append(KeepTogether([img("setup.png", 3.9 * inch), P("The SETUP dialog.", style_caption)]))
    f.append(table([
        ["Setting", "What it does"],
        ["Callsign", "Used to log in to the DX cluster and the Reverse Beacon Network, and to find your "
                     "own signal on RBN, PSKReporter and WSPR (tab B)."],
        ["Grid locator (QTH)", "Your Maidenhead locator (4, 6 or 8 characters, e.g. <b>QF22ne</b>). The "
                               "latitude/longitude it works out is shown underneath. Everything that "
                               "depends on where you are uses it: weather, sunrise and sunset, beam "
                               "headings, satellite passes, the nearest ionosondes and the map centre."],
        ["DX cluster host:port", "Which DX cluster to use (default <b>dxc.ve7cc.net:23</b>). Any "
                                 "DXSpider/AR-Cluster/CC-Cluster telnet node works."],
        ["Reverse Beacon Network", "Turn the CW/RTTY skimmer feed (port 7000) and the FT8/FT4 feed "
                                   "(port 7001) on or off."],
        ["Antenna wind alert at", "The gust speed that trips the wind alert on tab H (default 60 km/h)."],
        ["Satellite passes above", "Passes lower than this maximum elevation are left out of tab D "
                                   "(default 10&deg;)."],
        ["Text / panel size", "Scales text and controls from &times;0.8 to &times;1.5 for small or "
                              "large screens."],
        ["Licence level (Australia)", "Advanced, Standard or Foundation. Used to grey out spots you may "
                                      "not transmit on (tabs B and K) and as the starting level on tab N."],
        ["BoM warnings for", "Which state's Bureau of Meteorology warnings tab H lists."],
        ["BoM radar ID", "Which BoM rain radar tab H loops (default <b>IDR023</b>, Melbourne 128 km; "
                         "<b>IDR022</b> is the same radar at 256 km). The ID is in the address of the "
                         "radar's page on bom.gov.au."],
        ["APRS-IS feed / radius", "Turns tab L's APRS feed on or off, and how far around your QTH it "
                                  "collects stations (default 150 km). It only receives."],
        ["Show the MY SHACK tab", "Tab O shows the operator's own hotspots, switches and other LAN gear. "
                                  "Untick it to hide the tab, e.g. when the dashboard is given to another "
                                  "station that has none of that equipment."],
        ["Check for a newer ShackDash", "A few seconds after start the program asks GitHub whether a newer "
                                        "release exists. If so, an amber <b>UPDATE vX.Y AVAILABLE</b> button "
                                        "appears in the top bar; click it to open the download page. Nothing is "
                                        "downloaded or installed for you, and nothing is sent except the request "
                                        "itself. Untick to turn the check off (e.g. when offline)."],
    ], [1.65, 5.55]))

    # ------------------------------------------------------------------------------------------------
    f.append(CondPageBreak(3.2 * inch))
    f.append(P("The Top Bar and Tab Keys", style_h2))
    f.append(shot("topbar.png"))
    f.append(table([
        ["Item", "What it does"],
        ["Station line", "Your callsign, grid locator and the latitude/longitude used for calculations."],
        ["Clock", "Current time in UTC (the <i>z</i> suffix means UTC/Zulu)."],
        ["DATA lamp", "<b>DATA a/b</b>: how many internet sources are up to date out of the total. "
                      "<b>LIVE c/d</b>: how many streaming feeds (cluster, RBN and APRS) are connected. "
                      "Green = all fine, amber = up to three sources failing, red = more. Click the lamp "
                      "to open the SOURCES list."],
        ["REFRESH", "Fetch every source now instead of waiting for its next scheduled update."],
        ["SOURCES", "Lists every source with its status, age, refresh interval, size and credit, plus "
                    "the items not included yet (see Data Sources below)."],
        ["THEME", "Cycles the colour theme: SHACK (default), FLIGHT DECK, AMBER NIGHT, PHOSPHOR, DAYLIGHT."],
        ["SETUP", "Station settings (see above)."],
        ["&ndash; &nbsp; &#9634; &nbsp; CLOSE", "Minimise, maximise/restore, and close the window."],
        ["Tab keys A-O", "Pick a page (two rows; O is only there when MY SHACK is shown). The selected key has a lit LED and a blue outline. The app "
                         "remembers the last tab you used."],
    ], [1.65, 5.55]))
    f.append(CondPageBreak(1.6 * inch))
    f.append(P("Moving and sizing the window", style_h3))
    f.append(bullets([
        "Drag the top bar to move the window. Double-click it to maximise or restore.",
        "Drag the grip in the bottom-right corner to resize. Size and position are remembered.",
        "The line along the bottom credits the sources used on the current tab.",
    ]))
    f.append(CondPageBreak(1.6 * inch))
    f.append(P("Keyboard shortcuts", style_h3))
    f.append(table([
        ["Key", "Action"],
        ["1 ... 9, 0", "Jump to tab A ... I, and J"],
        ["Alt+A ... Alt+O", "Jump straight to the tab with that letter (Alt+O = My Shack)"],
        ["Ctrl+B, Ctrl+D ... Ctrl+O", "The same with Ctrl (Ctrl+A and Ctrl+C stay select-all and copy)"],
        ["Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab (reaches K-O)"],
        ["Ctrl+R", "Refresh all sources"],
        ["F11 / Esc", "Full screen on / off"],
    ], [1.65, 5.55]))
    f.append(CondPageBreak(1.6 * inch))
    f.append(P("Conventions used on every tab", style_h3))
    f.append(bullets([
        "<b>Panels</b> are the rounded frames with a title and a coloured dot. <b>Tiles</b> are the small "
        "screens with a big number. The small LED in a tile's corner lights when that value needs "
        "attention or is active.",
        "<b>Colours</b>: green = good or normal, amber = worth watching, red = poor, disturbed or alert. "
        "Grey or dim text = old or inactive.",
        "<b>Filter keys</b> (rows of small keys such as ALL / 160m / 80m) work like radio buttons. The lit "
        "one is in use.",
        "<b>Search boxes</b> filter a table as you type. Click the &times; in the box to clear it.",
        "<b>Tables</b>: click a row to select it. Where noted, double-click opens the web page behind it. "
        "Hover over a cell for extra detail where there is some.",
        "<b>Times</b>: a trailing <i>z</i> means UTC. Tab D and tab C show local time where noted.",
    ]))

    # ------------------------------------------------------------------------------------------------
    tab_section(f, "Tab A - Space Weather and HF Propagation", "tab_a.png",
                "Tab A. Solar and geomagnetic conditions and what they mean for HF.",
                "The sun drives HF propagation. This tab shows current solar activity, the state of the "
                "Earth's magnetic field, and measured ionospheric conditions near you.", [
        ["NOW tiles", "<b>SOLAR FLUX</b> (10.7 cm flux, sfu): higher means better upper-HF bands. Green "
                      "90+, amber 70-90, red below 70.<br/>"
                      "<b>SUNSPOTS</b>: daily sunspot number.<br/>"
                      "<b>A INDEX</b>: the day's geomagnetic disturbance. Green under 15 (quiet), amber "
                      "15-30, red 30+. The line underneath gives the field state (e.g. Quiet, Active, Storm).<br/>"
                      "<b>Kp NOW</b>: latest 3-hour planetary K index, 0-9. Green under 4, amber 4, red 5+ "
                      "(storm, shown as G1-G5).<br/>"
                      "<b>X-RAY</b>: solar X-ray class (A, B, C, M, X). M and X flares cause HF blackouts on "
                      "the daylit side of the Earth. The sub-line gives the 6-hour peak.<br/>"
                      "<b>SOLAR WIND</b>: speed in km/s (green under 500, amber to 700, red above) and density.<br/>"
                      "<b>Bz (GSM)</b>: north-south direction of the interplanetary magnetic field. A strong "
                      "negative (southward) Bz lets the solar wind couple in and drives storms. Green above "
                      "-5 nT, amber to -10, red below.<br/>"
                      "<b>PROTONS &ge;10 MeV</b>: in pfu. 10 pfu and above is an S1 radiation storm, which "
                      "absorbs HF over the polar regions.<br/>"
                      "<b>NOAA R &middot; S &middot; G</b>: NOAA's radio blackout, solar radiation and "
                      "geomagnetic storm scales now (0-5), with the next-24-hour probabilities.<br/>"
                      "<b>MUF NEAREST</b>: the maximum usable frequency for a 3000 km hop, measured by the "
                      "nearest ionosonde that reported in the last 3 hours."],
        ["HF BAND CONDITIONS", "N0NBH's calculated conditions for four band groups, day and night: Good "
                               "(green), Fair (amber), Poor (red). Underneath: geomagnetic field, band "
                               "noise level, and whether VHF aurora or sporadic-E is open."],
        ["PLANETARY Kp", "3-hourly Kp for the past three days and NOAA's forecast for the next three. "
                         "Solid bars are measured and faint dashed bars are forecast. G1-G5 on the right mark "
                         "storm levels."],
        ["GOES X-RAY FLUX", "24 hours of X-ray flux on a log scale. Amber is the long (0.1-0.8 nm) "
                            "channel used for flare classes, blue is the short channel. Dashed lines mark "
                            "the B, C, M and X levels. A spike to M or X means an HF fadeout."],
        ["SOLAR WIND", "24 hours of solar wind speed (top), and of Bt (total field, grey) with Bz (red) "
                       "below. The red-shaded area below zero is southward Bz."],
        ["PROTON FLUX", "24 hours of the &ge;10 MeV proton flux, with the S1 and S2 thresholds marked."],
        ["NEAREST IONOSONDES", "The closest ionosondes to your QTH (distance in km). <b>MUFd</b> is the "
                               "3000 km MUF, <b>foF2</b> the critical frequency (the highest frequency "
                               "returned straight up, which sets the limit for NVIS), and <b>hmF2</b> the F2 "
                               "layer height in km. <b>AGE</b> is how old the reading is. Dim rows are more "
                               "than an hour old."],
        ["SWPC ALERTS", "NOAA's recent alerts, watches and warnings. Red rows are alerts or warnings "
                        "issued in the last 24 hours. Click a row to read the full message below."],
        ["AURORA AUSTRALIS", "NOAA's OVATION model of the southern auroral oval (green = probability of "
                             "visible aurora), with the day/night shading and your QTH. When the oval "
                             "reaches your latitude, try 6 m and 2 m aurora contacts, and expect "
                             "degraded HF polar paths."],
    ], width=5.0 * inch)

    tab_section(f, "Tab B - Live Activity", "tab_b.png",
                "Tab B. The DX cluster, where your own signal is being heard, and which bands are open.",
                "Who is on the air right now, where your signal is getting to, and which bands are open "
                "from your area.", [
        ["DX CLUSTER", "Live spots from the DX cluster set in SETUP: UTC time, frequency in kHz, the "
                       "DX station, its country, who spotted it, the likely mode and the comment. The "
                       "list keeps the newest 1500 spots.<br/>"
                       "<b>Band keys</b>: show ALL bands, one HF band, 6 m, or VHF+ (everything above 6 m).<br/>"
                       "<b>SKIMMERS</b>: off by default. Turn it on to include automatic CW/RTTY skimmer "
                       "spots (spotter calls ending in <i>-#</i>).<br/>"
                       "<b>Search box</b>: matches the call, country, spotter or comment.<br/>"
                       "<b>Colours</b>: amber = a spot of <i>your</i> call, purple = a DXpedition currently "
                       "active per NG3K (tab E), green = spotted within the last 90 seconds, grey = outside "
                       "your licence privileges (hover to see).<br/>"
                       "The line above the table shows the cluster connection and the spot count."],
        ["WHERE ... IS HEARD (map)", "Every station that heard you in the last 6 hours, with a "
                                     "great-circle line from your QTH. Green = Reverse Beacon Network "
                                     "skimmers, blue = PSKReporter, purple = WSPR receivers, grey = WSPR "
                                     "stations <i>you</i> received."],
        ["WHO HEARS ME", "The same reports as a table: time, source (RBN, PSK, WSPR or WSPR-RX), the "
                         "other station, band, mode, SNR in dB, distance in km and where they are. "
                         "Covers RBN for 6 h, PSKReporter for the last hour and WSPR for 24 h. It's empty "
                         "until you transmit: call CQ on CW or FT8, or run WSPR, and watch it fill."],
        ["BAND ACTIVITY", "Uses PSKReporter reports from the last hour with one end in your grid field "
                          "(the first two letters of your locator, e.g. QF). Each cell counts the paths "
                          "between your area and one continent on one band. Brighter and warmer colours "
                          "mean more activity. This shows at a glance which band is open to where right "
                          "now. OC includes contacts within VK/ZL. The table below gives the longest path "
                          "seen on each band."],
        ["NCDXF / IARU BEACONS", "The 18 international beacons take turns on 14.100, 18.110, 21.150, "
                                 "24.930 and 28.200 MHz, 10 seconds each, repeating every 3 minutes. Each "
                                 "row shows who is on that frequency <b>now</b>, where they are, your beam "
                                 "heading, and who is next and when. Hover for distance and the long-path "
                                 "heading. Each beacon sends its call and then four dashes at 100 W, 10 W, "
                                 "1 W and 0.1 W. The weaker the dash you can hear, the better the path."],
    ], width=6.3 * inch)

    tab_section(f, "Tab C - Local: Time, Sun, Moon and Beam Headings", "tab_c.png",
                "Tab C, aimed at W1AW: short path (solid) and long path (dashed) on the grey-line map.",
                "Everything on this tab is calculated on your PC from your QTH and the clock, so it "
                "works without the internet.", [
        ["TIME &amp; SUN", "<b>UTC</b> and <b>LOCAL</b> clocks with date and time zone. <b>SUNRISE</b> "
                           "and <b>SUNSET</b> in local time, with civil dawn and dusk (sun 6&deg; below the "
                           "horizon) underneath. The LED lights while that event is still to come today. "
                           "<b>DAYLIGHT</b>: day length, with sunrise-sunset in UTC. <b>SUN AZ / EL</b>: "
                           "where the sun is now (azimuth / elevation)."],
        ["MOON &amp; EME", "<b>MOON</b>: percentage illuminated and phase name. <b>MOON AZ / EL</b>: "
                           "position now (LED lit when it is above the horizon). <b>RISE / SET</b>: the next "
                           "moonrise and moonset, local time. <b>EME LOSS</b>: extra moonbounce path loss "
                           "compared with the moon at perigee, from distance only (0 to about 2.3 dB; sky "
                           "noise not included). Green under 1 dB, amber to 1.6 dB, red above."],
        ["GREY LINE map", "World map centred on your longitude. Dark = night, clear = day, and the "
                          "amber band is the grey line (sun between 0&deg; and 6&deg; below the horizon), "
                          "where low-band DX is often enhanced. Markers show the sub-solar point (SUN), the "
                          "sub-lunar point (MOON) and your QTH. <b>Click anywhere</b> on the map to aim the "
                          "beam heading calculator there."],
        ["BEAM HEADING", "Type a <b>callsign or prefix</b> (uses the centre of that DXCC entity), a "
                         "<b>grid locator</b> (e.g. FN31pr), or <b>lat, lon</b> (e.g. -33.9, 151.2). "
                         "Shows the short-path and long-path headings in degrees, compass point and "
                         "distance, and draws both paths on the map. The line below names the target and "
                         "says whether the far end is in daylight, the grey line, or dark."],
        ["BEARINGS FROM MY QTH", "Short-path and long-path headings and distance to common DX areas, "
                                 "and whether each is currently in daylight, grey line or dark. Amber "
                                 "rows are in the grey line now."],
    ])

    tab_section(f, "Tab D - Satellites", "tab_d.png",
                "Tab D. Upcoming passes, the ISS tracker with Doppler-corrected frequencies, sky view and "
                "ground track.",
                "Pass predictions and live tracking for about 95 amateur satellites, worked out on your "
                "PC from CelesTrak orbital elements.", [
        ["PASSES OVER MY QTH", "Every pass in the next 24 hours that rises above the minimum elevation "
                               "set in SETUP. Columns: <b>AOS</b> (acquisition of signal, local time), "
                               "satellite, <b>MAX</b> elevation, <b>AZ</b> (azimuth at AOS &rarr; azimuth at "
                               "LOS), <b>MIN</b> (duration in minutes) and <b>STARTS</b> (NOW or time until "
                               "AOS). Amber = in progress, green = a high pass (max 45&deg; or more). Type "
                               "in the search box to show one satellite (e.g. <i>ISS</i>, <i>SO-50</i>, "
                               "<i>RS-44</i>). <b>Click a pass</b> to track that satellite. The list "
                               "recalculates every 30 minutes."],
        ["TRACKING", "Live position of the selected satellite (the ISS by default): azimuth, elevation "
                     "(LED lit when it is above your horizon), range and altitude, and range rate. "
                     "Positive range rate means it is moving away. The 2 m figure is the Doppler shift at "
                     "145.8 MHz. The table lists the satellite's active amateur transmitters from SatNOGS: "
                     "<b>DOWN</b> is the published downlink, and <b>RX NOW</b> is the frequency to tune "
                     "your receiver to right now. <b>UP</b> is the published uplink, and <b>TX NOW</b> is "
                     "the frequency to transmit on so you arrive on frequency. These update every second."],
        ["SKY VIEW", "The selected pass drawn on a polar sky chart: the outer ring is the horizon, rings "
                     "at 30&deg; and 60&deg;, and the centre is straight up. AOS (green) and LOS (red) "
                     "are marked, and the amber dot is where the satellite is now while it is up. "
                     "Point your antenna along this track."],
        ["GROUND TRACK", "The ISS (amber) and the selected satellite (green) on the world map. Dashed "
                         "= the next orbit. The ring is the radio footprint: you can work the satellite "
                         "while your QTH is inside it."],
        ["SATNOGS", "The latest successful observations from the worldwide SatNOGS ground-station "
                    "network. Shows which satellites are active and being heard."],
    ])

    tab_section(f, "Tab E - DX and Contest Calendar", "tab_e.png",
                "Tab E. Contests, DXpeditions and the DXCC Most Wanted list.",
                "What is on this weekend, which DXpeditions are on the air, and which countries are rarest.", [
        ["CONTESTS", "From the WA7BNM Contest Calendar. <b>ON NOW</b> shows contests running now, and "
                     "<b>NEXT 8 DAYS</b> adds everything starting within 8 days. <b>WHEN</b> reads "
                     "<i>ON &middot; 11h left</i> or <i>in 2d</i>. <b>UTC</b> gives the start and end "
                     "(day and time in UTC). Amber rows are running now. <b>Double-click</b> a contest to "
                     "open its rules page."],
        ["DXPEDITIONS &amp; DX OPERATIONS", "From NG3K's Announced DX Operations. <b>ACTIVE</b> shows "
                                            "operations running now, <b>UPCOMING</b> shows those not "
                                            "started yet, and <b>ALL</b> shows the full list. Columns: "
                                            "status, DXCC entity, callsign, dates and QSL route. Purple = "
                                            "active. A green <b>SPOTTED</b> status (with the kHz) means "
                                            "the station has been spotted on the DX cluster since the "
                                            "dashboard started: go and look for it. Double-click to open "
                                            "NG3K's page."],
        ["DXCC MOST WANTED", "Club Log's ranking of the most-wanted DXCC entities (1 = rarest), with "
                             "continent and main prefix. Use the search box to find an entity's rank."],
    ])

    tab_section(f, "Tab F - Digital Voice Networks", "tab_f.png",
                "Tab F. Reflector and talkgroup directories, filtered for Australia.",
                "Directories for XLX, D-STAR REF/DCS/XRF, NXDN, P25, DMR BrandMeister and Yaesu System Fusion "
                "(YSF). Each panel has a search box; the XLX, YSF and BrandMeister ones are preset to Australian "
                "entries. Clear a box to see everything.", [
        ["XLX / D-STAR REFLECTORS", "Every registered XLX multi-mode reflector: name, country, when it "
                                    "last reported in to the XLX registry, and its description. Green = "
                                    "reported within 30 minutes (up and running), dim = not heard from "
                                    "for over a day. The newest are listed first. <b>Double-click</b> a "
                                    "reflector to open its web dashboard, which shows who is linked."],
        ["D-STAR REF &middot; DCS &middot; XRF &middot; NXDN &middot; P25", "Pi-Star's reflector lists for the "
                                    "other networks: pick one with the keys (D-STAR REF, DCS, XRF, NXDN, P25) and "
                                    "search by number or host. Reflectors one of your own hotspots is linked to "
                                    "right now (from tab O) are listed first, in green, with the hotspot's name. The "
                                    "lists give the reflector and its address only; they carry no descriptions."],
        ["BRANDMEISTER TALKGROUPS", "BrandMeister's talkgroup directory: number and name. Search by "
                                    "name (e.g. <i>Victoria</i>) or number (e.g. <i>5053</i>)."],
        ["YSF (FUSION) REFLECTORS", "The YSF reflector list used by Pi-Star/WPSD hotspots: ID, name, "
                                    "description and host:port."],
    ], [box("Live BrandMeister last-heard (who is talking now) is not included yet. It needs "
            "BrandMeister's streaming feed, which is still to be worked out.")])

    tab_section(f, "Tab G - VHF/UHF Propagation", "tab_g.png",
                "Tab G. The Hepburn tropospheric ducting forecast, VHF spots and paths.",
                "Tropospheric ducting forecasts and VHF/UHF activity.", [
        ["TROPOSPHERIC DUCTING FORECAST", "William Hepburn's tropo ducting index for Australia and New "
                                          "Zealand. Cool colours = normal conditions, while yellow, red "
                                          "and white = increasingly strong ducting, meaning long-distance "
                                          "VHF/UHF paths along those areas. Move the slider to step "
                                          "through the forecast. The label shows each frame's valid time "
                                          "in UTC and local time, and it opens on the frame nearest now. "
                                          "<b>PLAY</b> animates the frames and <b>STOP</b> halts them."],
        ["VHF / UHF SPOTS", "DX cluster spots at 50 MHz and above. Use the keys to show all VHF+ or a "
                            "single band (6 m, 4 m, 2 m, 70 cm). <b>km</b> is worked out from grid "
                            "locators in the comment when present, otherwise from the two countries' "
                            "centres. The line above gives N0NBH's VHF outlook (aurora, sporadic-E) and "
                            "the current aurora latitude."],
        ["VHF+ PATHS", "The spots from the last 3 hours as lines on the map. Purple = 6 m, green = 2 m, "
                       "amber = 4 m / 70 cm. Clusters of lines show where a band is open."],
    ], [box("VHF spots are only collected while the dashboard is running, so this tab starts empty "
            "and fills over time. Sporadic-E and tropo openings show up here first.")])

    tab_section(f, "Tab H - Weather and Site Safety", "tab_h.png",
                "Tab H. Conditions at your QTH, the antenna wind alert, storm risk, BoM radar and warnings.",
                "Local weather for your QTH, with the two things that matter for antennas: wind and "
                "lightning risk.", [
        ["NOW AT MY QTH", "Temperature, feels-like, humidity (with cloud cover), wind speed and direction "
                          "it is coming from, gusts, sea-level pressure, rain in the last hour, and the "
                          "sky condition. The GUSTS tile turns amber at 70% of your alert level and red "
                          "at it."],
        ["ANTENNA WIND ALERT", "<b>CLEAR</b> (green): gusts stay below your alert level for the next 12 "
                               "hours. <b>COMING</b> (amber): the forecast reaches it, with when. "
                               "<b>NOW</b> (red): it is gusting above it now. Set the level in SETUP "
                               "to suit your tower or mast."],
        ["THUNDERSTORM RISK", "An estimate for the next 12 hours from the forecast. <b>HIGH</b>: "
                              "thunderstorms forecast. <b>MODERATE</b>: high storm energy (CAPE over "
                              "1500 J/kg) with a good chance of rain. <b>LOW</b>: some storm energy. "
                              "<b>MINIMAL</b>: none."],
        ["3-DAY OUTLOOK", "Conditions, minimum and maximum temperature, rain total and maximum gust for "
                          "today and the next two days. Red rows are days when gusts reach your alert "
                          "level."],
        ["WIND &amp; GUSTS / TEMPERATURE", "12 hours back and 48 hours ahead. The dashed amber line is "
                                           "now. On the wind plot, blue is the mean wind, red is gusts, "
                                           "and the dashed red line is your alert level."],
        ["STORM FUEL", "CAPE (convective energy that feeds thunderstorms, J/kg) in red, and the chance of "
                       "rain (in %, multiplied by 10 to share the scale) in blue."],
        ["BoM RAIN RADAR", "The last hour of the Bureau of Meteorology radar chosen in SETUP, looping, "
                           "with a pause on the newest frame. The line underneath gives the frame's local "
                           "time and how old the newest one is. Storm cells show as yellow, red and black "
                           "blobs: watch whether they move towards you."],
        ["BoM WARNINGS", "Current warnings for the state chosen in SETUP. Red = severe weather or "
                         "thunderstorms, amber = wind."],
    ], [warn("The storm risk is a <b>forecast estimate</b>, not live lightning detection. If you hear "
             "thunder or see lightning, disconnect and ground your antennas regardless of what the "
             "dashboard says.")])

    tab_section(f, "Tab I - News", "tab_i.png",
                "Tab I. Headlines from four amateur-radio news feeds, with the story on the right.",
                "Recent news from the Wireless Institute of Australia, the ARRL, Amateur Radio "
                "Newsline and DX-World.", [
        ["HEADLINES", "All stories, newest first: date, source and headline. Green = published in the "
                      "last 24 hours. The keys show ALL feeds or one (WIA, ARRL, NEWSLINE, DX-WORLD). "
                      "The search box filters on headline and story text."],
        ["STORY", "Click a headline to read it here. <b>OPEN IN BROWSER</b> (or double-clicking the "
                  "headline) opens the full article on the source's website."],
    ])

    tab_section(f, "Tab J - The Sun and the Month Ahead", "tab_j.png",
                "Tab J. NOAA's 27-day outlook, the solar cycle, D-RAP absorption and live solar images.",
                "Planning ahead: what NOAA expects over the next solar rotation, where the solar cycle is, and "
                "what the sun looks like right now.", [
        ["PLANNING AHEAD tiles", "<b>MAX Kp NEXT 7 DAYS</b> and <b>FLUX NEXT 7 DAYS</b> from the outlook. "
                                 "<b>QUIET DAYS AHEAD</b>: days with Kp 2 or less (low noise, best for DX). "
                                 "<b>NEXT STORM DAY</b>: the first day with Kp 5+ forecast. <b>SMOOTHED "
                                 "SSN</b>: the latest 13-month smoothed sunspot number and the cycle's peak. "
                                 "<b>PREDICTED SSN NOW</b>: NOAA's forecast for this month."],
        ["NOAA 27-DAY OUTLOOK", "Forecast 10.7 cm flux (amber) and planetary A index (blue, dashed) for "
                                "27 days, with the largest Kp expected each day as bars below. It is issued "
                                "every Monday. Because the sun turns once in about 27 days, recurring coronal "
                                "holes and active regions show up here in advance."],
        ["SOLAR CYCLE", "Monthly sunspot number (grey) and the 13-month smoothed value (amber) since 2009, "
                        "with NOAA's prediction (blue, dashed) and its range (shaded)."],
        ["D-RAP", "NOAA's D-region absorption map: the colour is the highest frequency losing 1 dB. A "
                  "clear map means no fade-out. After a flare the sunlit side colours in; during a proton "
                  "event the polar caps do."],
        ["THE SUN NOW", "Pick an image: AIA 193 (coronal holes show as dark areas; they bring fast "
                        "solar wind and a Kp rise about 3 days later), AIA 171, AIA 304 (prominences), AIA 131 "
                        "(flares), SUNSPOTS, MAGNETO (magnetogram), and the LASCO C2/C3 coronagraphs, where a "
                        "halo around the disk means an Earth-directed CME. Images refresh every 15 minutes."],
    ])

    tab_section(f, "Tab K - Portable Activators", "tab_k.png",
                "Tab K. Park and summit activators on air now, merged from three spotting networks.",
                "Who is operating portable right now. Spots from Parks on the Air, WWFF and ParksnPeaks "
                "(the VK spotting site, which also carries SOTA) are merged: one row per callsign and "
                "frequency, with every program it counts for.", [
        ["Tiles", "Activators on air in the last hour, how many are in VK, the nearest one to you, and "
                  "the counts per program."],
        ["ACTIVATOR SPOTS", "Keys filter by program (ALL, POTA, WWFF, SOTA), region (WORLD, VK, VK + ZL, "
                            "OCEANIA) and band. The search box matches call, reference, park and mode. "
                            "<b>km</b> and <b>BRG</b> are from your QTH; a <b>~</b> means the country "
                            "centre was used. Green = spotted in the last 5 minutes. Grey = outside your "
                            "licence privileges. <b>Click a row</b> for its beam headings, a path on the map, "
                            "and a privilege check."],
        ["WHERE THEY ARE", "The activators whose spots carry coordinates (POTA and WWFF). Green POTA, "
                           "amber WWFF."],
    ], [box("SOTAwatch's own API asks apps like this for prior approval, so SOTA spots come through "
            "ParksnPeaks instead.")])

    tab_section(f, "Tab L - APRS Around My QTH", "tab_l.png",
                "Tab L. APRS stations, objects and weather stations heard on APRS-IS near your QTH.",
                "A live APRS picture of your area from the APRS-IS internet network. The dashboard logs "
                "in read-only and never transmits. Stations are collected while it runs, so the map fills "
                "over time.", [
        ["APRS AROUND MY QTH", "Map with range rings (a third, two-thirds and all of the radius set in "
                               "SETUP). Amber = mobile, green = fixed, blue = weather, purple = digipeaters "
                               "and gateways, grey = nothing heard for 30 minutes. Moving stations leave a "
                               "trail. The nearest 30 are labelled. The line on top shows the connection. <b>Background:</b> a dark street map (OpenStreetMap tiles, downloaded as needed and cached in "
                               "%APPDATA%\\ShackDash\\tiles) shows roads, towns and forests; only the tile positions you view are sent to "
                               "the tile server. Untick <b>Detailed APRS map background</b> in SETUP for the plain land outline. <b>Zoom and pan:</b> roll the mouse wheel to zoom in or out around the pointer, drag to move the map, and double-click to return to the full view around your QTH."],
        ["STATIONS &middot; OBJECTS &middot; WEATHER", "Everything heard, newest first: what it is (from "
                                                        "its APRS symbol), distance, bearing, when last "
                                                        "heard, packet count, speed and its comment or "
                                                        "weather. Filter keys: ALL, MOBILE, FIXED, WX, "
                                                        "DIGI / IGATE, OBJECTS. Click a row for its "
                                                        "details and a highlighted track."],
        ["PACKETS AS THEY ARRIVE", "The raw packets. <b>MESSAGES + BULLETINS</b> shows only APRS "
                                   "messages. Red = a message addressed to your call."],
    ])

    tab_section(f, "Tab M - Planner", "tab_m.png",
                "Tab M. Meteor showers, EME days, ARISS school contacts and SSTV events.",
                "Things worth planning a week or a month ahead, worked out for your QTH.", [
        ["METEOR SHOWERS", "The major showers in date order with the peak (UTC), days to go, ZHR, the "
                           "highest the radiant gets at your QTH on the peak day (MAX EL), the best local "
                           "time, hours it is up, where it is now (EL NOW) and the meteor speed. Green = "
                           "within 3 days of peak, amber = within 2 weeks, grey = never up from your QTH. "
                           "Daytime showers (Arietids, zeta Perseids, Sextantids) are radio-only and good "
                           "for meteor scatter. Values are approximate (IMO working list)."],
        ["EME PLANNER", "The next 4 weeks: <b>LOSS</b> is the extra path loss over perigee (distance only), "
                        "<b>DEC</b> the moon's declination, <b>HRS UP</b> how long it is above 5&deg; at "
                        "your QTH, <b>MAX EL</b> its highest elevation and <b>SUN SEP</b> how far it is "
                        "from the sun (under 15&deg; adds sun noise). GOOD / FAIR / POOR combines them. "
                        "The chart plots the loss and the hours up."],
        ["ARISS SCHOOL CONTACTS", "Scheduled ISS school contacts, in UTC and local time, with the crew "
                                  "member. <b>ISS FROM MY QTH</b> checks the ISS pass at that time: if it "
                                  "is in range, you can listen to the ISS side on 145.800 MHz FM."],
        ["ARISS SSTV EVENTS", "Announced ISS slow-scan TV events with dates, frequency and mode."],
    ])

    tab_section(f, "Tab N - Tools", "tab_n.png",
                "Tab N. Callsign lookup, public KiwiSDR receivers, and the Australian licence privileges.",
                "Station tools that need no account.", [
        ["CALLSIGN LOOKUP", "Type a callsign (or a grid locator) and press Enter. Shows the DXCC entity, "
                            "continent, CQ and ITU zones, the local time there, whether the station uses "
                            "LoTW and when it last uploaded, and the short- and long-path beam headings and "
                            "distance. For US calls it also shows the FCC licence record from callook.info. The "
                            "buttons open the call's QRZ.com, HamQTH and Club Log pages or its PSKReporter map in "
                            "your browser.<br/>"
                            "<b>Location</b>: the line under the headings says where the distance is measured to, "
                            "best first: the station's <b>APRS position</b> (tab L); the <b>Maidenhead locator</b> "
                            "its own FT8/WSPR software sends, found on PSKReporter (asked for the last 12 hours); "
                            "its <b>FCC licence address</b> (US calls); its <b>call area</b> (VK1-8, ZL1-4, "
                            "VE1-9, JA0-9, W0-9, using the area's main city); and only as a last resort the "
                            "<b>centre of its country</b>. Green = locator or better, amber = call area, red = "
                            "country centre."],
        ["MY LICENCE PRIVILEGES", "The bands, power limits and bandwidth limits for Advanced, Standard or "
                                  "Foundation, from the Amateur Stations Class Licence 2023 (Schedule 2). "
                                  "Type a frequency underneath to check it: <i>7.150</i> or <i>146.5</i> "
                                  "are read as MHz, <i>14074</i> as kHz, or add kHz/MHz/GHz. pX = peak "
                                  "envelope power, pY = mean power."],
        ["PUBLIC KIWISDR RECEIVERS", "Online KiwiSDR web receivers sorted by distance: <b>NEAR ME</b>, "
                                     "<b>NEAR THE DX</b> (the station you looked up) or only those with "
                                     "<b>OPEN SLOTS</b>. Grey = all listening slots in use. "
                                     "<b>Double-click</b> one to open it in your browser, then tune to "
                                     "your own frequency to hear how you get out."],
    ], [box("VK callsign holders cannot be looked up: since the 2024 class licence, individual amateur "
            "licences are no longer in the ACMA register data.")])

    tab_section(f, "Tab O - My Shack (optional)", "tab_o.png",
                "Tab O. Hotspots, HF matrix switches and other LAN gear, polled every 10 seconds.",
                "The operator's own equipment on the local network. It is optional: untick <b>Show the "
                "MY SHACK tab</b> in SETUP to hide it, and use <b>EDIT DEVICES</b> to list your own gear.", [
        ["Tiles", "How many devices answered (and which did not), hotspots linked to a reflector, HF "
                  "matrix boxes up and any alarm, the hottest hotspot CPU, the last call heard on any "
                  "hotspot, and the last poll time. <b>POLL NOW</b> polls at once."],
        ["Device cards", "One card per device; the dot and frame turn red when it does not answer. Each "
                         "card gives the type, the address used and how it was found (<i>name</i>, "
                         "<i>beacon</i>, <i>fixed</i> or <i>last known</i>) and the response time.<br/>"
                         "<b>WPSD hotspot</b>: the reflector/network it is linked to and for how long, CPU "
                         "temperature, load, uptime and the last station heard. <b>HF matrix box</b>: which "
                         "antenna each radio is switched to, temperatures, supply voltage and alarms. "
                         "<b>Shack Clock</b>: when it last synced to NTP, its brightness setting, WiFi "
                         "signal and uptime (from the clock's own page, http://shackclock.local/). "
                         "<b>Hotspot Monitor</b> (the Nextion edition, hotspotmon-nx.local): which hotspots it "
                         "shows and whether each is online. A hotspot renamed on the monitor's touch keyboard "
                         "takes the same name here, on its card and in the device list. A name you type in "
                         "EDIT DEVICES stays until that hotspot is next renamed on the monitor. "
                         "<b>Web device</b> / <b>LAN device</b>: up or down by web page or ping. A box that "
                         "answers ping but not on the web says so."],
        ["LAST HEARD ACROSS MY HOTSPOTS", "The last-heard lists of all hotspots merged, newest first. "
                                          "Amber = heard over RF, green = within 5 minutes."],
        ["EDIT DEVICES", "Add, remove and reorder devices and set each one's name, type and host "
                         "(<i>name.local</i>, a plain name or an IP address). The list starts empty; it is "
                         "saved with your settings. When a name stops resolving, the last address that answered is "
                         "used, and it is kept up to date automatically."],
    ], [box("A hotspot (WPSD or Pi-Star) needs the small <b>m5status.php</b> status page installed on it: "
            "double-click <b>hotspot\\install_hotspot.bat</b>, type the hotspot's name or IP and its "
            "password (factory default <i>raspberry</i>). On WPSD it also sets up a timer that puts the page "
            "back whenever WPSD's own updates remove it. HF matrix "
            "boxes are also found by the UDP discovery beacon they broadcast on port 51500; the first time "
            "the dashboard listens for it, Windows may ask whether to allow it on private networks.")])

    # ------------------------------------------------------------------------------------------------
    f.append(PageBreak())
    f.append(P("Data Sources", style_h2))
    f.append(P("Click <b>SOURCES</b> (or the DATA lamp) to see where every piece of data comes from and "
               "whether it is working."))
    f.append(shot("sources.png", caption="The SOURCES dialog."))
    f.append(bullets([
        "<b>STATUS</b>: OK (up to date), fetching, cached (showing the saved copy from an earlier "
        "run, usually just after starting), waiting (not fetched yet) or ERROR (with the reason in the "
        "right-hand column). A failed source retries every 2 minutes (or at its normal interval if the "
        "server said it was getting too many requests).",
        "<b>EVERY</b>: how often it is refreshed. Sources are polled no faster than their providers "
        "ask for.",
        "<b>STREAMING FEEDS</b>: the DX cluster, the two Reverse Beacon Network connections and APRS-IS, "
        "with the number of lines received. They reconnect by themselves if dropped.",
        "<b>LATER</b>: data that could be added in future but needs an API key or account, has "
        "licence limits, or couldn't be made to work yet.",
    ]))
    f.append(table([
        ["Tab", "Sources", "Refresh"],
        ["A", "NOAA Space Weather Prediction Center; N0NBH (hamqsl.com); KC2G / GIRO ionosondes",
         "5-15 min"],
        ["B", "DX cluster and Reverse Beacon Network (live telnet); PSKReporter; WSPR (wspr.live)",
         "live / 10-15 min"],
        ["C", "Calculated on the PC; AD1C country files for callsign lookups", "weekly (prefixes)"],
        ["D", "CelesTrak orbital elements; SatNOGS transmitter list and observations", "6 h / daily / 15 min"],
        ["E", "WA7BNM Contest Calendar; NG3K Announced DX Operations; Club Log", "6 h / daily"],
        ["F", "XLX registry; BrandMeister API; Pi-Star host lists (YSF, D-STAR REF/DCS/XRF, NXDN, P25)",
         "30 min - daily"],
        ["G", "William Hepburn (dxinfocentre.com); DX cluster; N0NBH", "3 h / live"],
        ["H", "Open-Meteo; Bureau of Meteorology radar (anonymous FTP) and warnings", "15 / 6 / 10 min"],
        ["I", "WIA, ARRL, Amateur Radio Newsline, DX-World RSS", "1 h"],
        ["J", "NOAA SWPC (27-day outlook, solar cycle, D-RAP); NASA SDO; SOHO LASCO", "6 h / daily / 10-15 min"],
        ["K", "Parks on the Air; WWFF Spotline; ParksnPeaks", "2 min"],
        ["L", "APRS-IS (aprs2.net), receive only", "live"],
        ["M", "ARISS (contacts, SSTV); calculated on the PC; CelesTrak for the ISS", "6 h"],
        ["N", "AD1C country files; ARRL LoTW activity; callook.info; KiwiSDR list; Class Licence 2023",
         "weekly / on demand / 6 h"],
        ["O", "Your own devices on the LAN", "10 s"],
    ], [0.5, 5.2, 1.5]))

    # ------------------------------------------------------------------------------------------------
    f.append(CondPageBreak(3 * inch))
    f.append(P("Troubleshooting", style_h2))
    f.append(table([
        ["Problem", "What to do"],
        ["DATA lamp amber or red", "Open SOURCES and read the ERROR column. <i>getaddrinfo failed</i> "
                                   "or <i>timed out</i> is a network or DNS hiccup and clears itself on the "
                                   "next retry (every 2 minutes). Click REFRESH to retry at once."],
        ["LIVE shows 0 or the cluster says offline", "Check the callsign in SETUP (clusters need it to log "
                                                     "in). Try another cluster, e.g. "
                                                     "<b>dxc.w3lpl.net:7373</b>. The feed retries by itself, "
                                                     "waiting longer each time up to 5 minutes."],
        ["WHO HEARS ME is empty", "Normal until you transmit. PSKReporter is only asked every 15 minutes, "
                                  "so allow time after calling CQ."],
        ["Times or headings look wrong", "Check the grid locator in SETUP. The PC's clock and time zone "
                                         "must also be correct: satellite and sun positions depend on "
                                         "them."],
        ["Few or no satellite passes", "Lower <b>Satellite passes above</b> in SETUP, and clear the "
                                       "search box on tab D."],
        ["Text too small or too large", "Change <b>Text / panel size</b> in SETUP, or maximise the window."],
        ["Tab L stays empty", "APRS-IS only sends packets as stations transmit, so a quiet area takes a "
                              "while to fill. Check <b>APRS-IS feed</b> is ticked in SETUP and the line above "
                              "the map says <i>connected</i>. Increase the radius if needed."],
        ["A My Shack device shows red", "Check it is powered and on the network. If it moved to a new "
                                        "address and its name does not resolve, put the new IP address in "
                                        "EDIT DEVICES."],
        ["My Shack is empty and the top bar says SETTINGS FILE UNREADABLE",
         "ShackDash could not read its settings file at start-up (another program had it open, for "
         "example). Your settings are not lost: nothing is saved in that session, so close ShackDash and "
         "start it again. The reason is written to <b>load_error.txt</b> in the settings folder."],
    ], [2.0, 5.2]))
    f.append(Spacer(1, 6))
    f.append(P("Settings are stored in <b>%APPDATA%\\ShackDash\\config.json</b>, and the saved copies "
               "of each source in <b>%APPDATA%\\ShackDash\\cache</b>. Deleting the cache folder is "
               "safe; it is rebuilt on the next start. Each time the settings are saved, the previous "
               "version is kept as <b>config.backup.json</b>: to go back to it, close ShackDash and "
               "copy it over config.json. Settings from before the rename (in "
               "<b>%APPDATA%\\ShackDashboard</b>) are copied across on the first start."))
    f.append(Spacer(1, 6))
    f.append(box("Data courtesy of NOAA SWPC, N0NBH (hamqsl.com), KC2G (prop.kc2g.com) and the GIRO "
                 "ionosonde network, PSKReporter (N1DQ), the Reverse Beacon Network, wspr.live, AD1C "
                 "(country-files.com), CelesTrak, SatNOGS / Libre Space Foundation, WA7BNM, NG3K, Club Log, "
                 "the XLX registry, BrandMeister, Pi-Star, William Hepburn (dxinfocentre.com), Open-Meteo "
                 "(CC BY 4.0), the WIA, the ARRL, Amateur Radio Newsline and DX-World, the Bureau of "
                 "Meteorology, NASA SDO (AIA and HMI teams), ESA/NASA SOHO, Parks on the Air, WWFF, "
                 "ParksnPeaks, APRS-IS (aprs2.net), ARISS, ARRL LoTW, callook.info and the kiwisdr.com "
                 "receiver list. Coastlines: Natural Earth."))

    doc.build(f, onFirstPage=footer, onLaterPages=footer)
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    build()
