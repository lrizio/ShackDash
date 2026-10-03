# Hotspot status page for MY SHACK

ShackDash's tab O (MY SHACK) shows each hotspot's link, CPU temperature, uptime and
last heard. It gets them from a small status page, `m5status.php`, that has to be installed
on each hotspot once. Works on **WPSD** and **Pi-Star**.

## Install (from a Windows PC)

1. The PC and the hotspot must be on the same network, and SSH must be on (it is by default).
2. Double-click **install_hotspot.bat** and type the hotspot's name or IP, e.g. `pi-star.local`
   or `192.168.1.50`. List several with commas.
3. Type the hotspot password when asked, two or three times per hotspot (factory default: `raspberry`;
   on Pi-Star it is the Remote Access Password from its Configuration page).
4. In ShackDash: tab O > **EDIT DEVICES** > **ADD**, set TYPE to **WPSD hotspot** (also
   used for Pi-Star) and HOST to the same name or IP.

From PowerShell: `.\install_hotspot.ps1 pi-star.local, 192.168.1.51 -User pi-star`

Check that it worked by opening `http://<hotspot>/m5status.php` in a browser. It should show JSON.

Handing the dashboard to another station? `build/` holds a ready copy of these files plus
`READ ME FIRST.txt` (step-by-step for Pi-Star). Re-copy them there after changing anything here.

## What the installer does

| | WPSD | Pi-Star |
|---|---|---|
| Copies `m5status.php` to `/var/www/dashboard/` | yes | yes |
| SD card | left read-write (WPSD runs that way) | made writable for the install, back to read-only after |
| Self-heal timer | yes: WPSD's SlipStream diagnostics delete extra files from the dashboard folder, so `ensure-m5status.timer` restores it from `/home/pi-star/dstar-web/` every 30 s | no: nothing deletes it |

Running the installer again is safe; use it to update `m5status.php` or after a card reflash
(a reflash wipes the page and the timer).

## Manual install (no Windows)

```bash
scp m5status.php install_m5status.sh pi-star@pi-star.local:/tmp/
ssh -t pi-star@pi-star.local "cd /tmp && sudo bash install_m5status.sh"
```

## Notes

* Tested on WPSD (Raspbian 13). On Pi-Star the file layout is the same, but its older MMDVMHost /
  ircDDBGateway builds may word some log lines differently. If the page answers but `link` or
  `lastheard` stays empty, send a few lines of `/var/log/pi-star/MMDVM-*.log` and
  `ircDDBGateway-*.log`.
* DMR callsigns are looked up from the hotspot's own `/usr/local/etc/DMRIds.dat`.
* The master copy of `m5status.php` is `M5Monitor/pi/m5status.php` in HamProjects; this is a copy.
