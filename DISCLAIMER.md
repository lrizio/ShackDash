# Disclaimer

ShackDash is a free, non-commercial hobby project written by an amateur radio operator for other
amateurs. By downloading, installing or using it you accept the terms below. If you do not accept
them, do not use the software.

## No warranty

ShackDash, its hotspot add-on and its documentation are provided **"as is" and "as available"**,
without warranty of any kind, express or implied, including fitness for a particular purpose,
accuracy, reliability, availability or non-infringement. The full terms are in the
[MIT License](LICENSE).

## Limitation of liability

To the maximum extent permitted by law, the author and contributors are not liable for any direct,
indirect, incidental, special, consequential or other loss or damage arising from the use of, or
inability to use, ShackDash. This includes loss of data, damage to equipment or software, missed
contacts, licence infringements, injury or property damage. You use it entirely at your own risk.
Nothing here excludes any right that cannot be excluded under the consumer law that applies to you.

## Not for safety-of-life use

Weather, wind alerts, thunderstorm risk, rain radar, warnings, space-weather and propagation data
are shown **for general hobby interest only**. They may be late, incomplete, cached or wrong.
**Never rely on ShackDash** to decide whether it is safe to climb a tower, raise or lower an
antenna, operate portable, travel, or protect people or property. Always check official sources
(for example your national weather service and emergency services) directly.

## Third-party data and services

Almost everything ShackDash displays comes from third-party websites and services (NOAA, NASA,
the Bureau of Meteorology, Open-Meteo, CelesTrak, SatNOGS, PSKReporter, the Reverse Beacon
Network, DX clusters, APRS-IS, POTA, WWFF, ParksnPeaks, Club Log, hamqsl.com and others; see the
SOURCES button in the program for the full list and credits).

* The author does not control, endorse or guarantee any of these services or their data.
* Services can change, rate-limit or shut down at any time, and a tab may stop working without notice.
* All data remains the property of its owners. Use of each service is subject to its own terms;
  you are responsible for complying with them.
* ShackDash is **not affiliated with, endorsed by or sponsored by** any of these organisations.
  All names, logos and trademarks belong to their respective owners and are used only to identify
  the data source.

## Licence conditions and frequency information

Band plans, licence privileges (including the Australian Class Licence tables) and frequency
checks are a convenience only and may be out of date or incomplete. **They are not legal advice.**
Every operator is solely responsible for operating within the conditions of their own licence and
the regulations of their country. Always confirm against your regulator's official documents.

## Hotspot add-on

The optional installer in `hotspot/` copies a small status page (`m5status.php`) to Pi-Star or
WPSD hotspots on your own network, and on WPSD adds a timer that restores it. It changes files on
your hotspot. Back up your hotspot (or its SD card) before using it, and only run it on devices you
own or administer. It has been tested on WPSD; the Pi-Star path has had limited testing.

## Network use and privacy

* ShackDash does not collect telemetry, analytics or personal data, and has no server of its own.
  The author receives nothing from your copy of the program.
* To fetch data it connects directly from your PC to the services listed above. Some requests
  necessarily include information you entered in SETUP. For example, your callsign is used to
  log in (receive-only) to DX clusters, the Reverse Beacon Network and APRS-IS, and to ask
  PSKReporter who hears you. Your grid locator or approximate position is used for local weather,
  satellite passes and distance calculations. Those services handle that data under their own
  privacy policies.
* The MY SHACK tab only talks to devices on your own local network that you add yourself.
* Settings are stored only on your PC, in `%APPDATA%\ShackDash`.
* ShackDash never transmits on any radio. The APRS feature is receive-only.

## Unsigned software

The Windows program is not code-signed, so Windows SmartScreen may warn you the first time you run
it. Only download ShackDash from this project's official GitHub page. If you prefer, you can run it
directly from the source code instead.

## Changes

These terms may be updated with new releases. The version included with the release you downloaded
applies to that release.
