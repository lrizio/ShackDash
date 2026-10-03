#!/bin/bash
# Installs m5status.php (the JSON status page ShackDash's MY SHACK tab reads)
# on a WPSD or Pi-Star hotspot. Run on the hotspot as root, from the folder holding
# m5status.php:   sudo bash install_m5status.sh
#
# WPSD:     its SlipStream diagnostics task resyncs /var/www/dashboard and deletes any
#           file that is not part of WPSD, so a keeper copy goes in /home/pi-star/dstar-web
#           and a 30 s systemd timer (ensure-m5status) puts it back whenever it goes missing.
# Pi-Star:  the SD card runs read-only; it is made writable for the install and put back
#           to read-only afterwards. No SlipStream there, so no timer.
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
WEB=/var/www/dashboard
KEEP=/home/pi-star/dstar-web
ENSURE=/home/pi-star/ensure-m5status.sh

[ "$(id -u)" = 0 ] || { echo "Run as root: sudo bash $0"; exit 1; }
[ -f "$HERE/m5status.php" ] || { echo "m5status.php not found next to this script"; exit 1; }
[ -d "$WEB" ] || { echo "$WEB not found - is this a WPSD or Pi-Star hotspot?"; exit 1; }

if [ -f /etc/WPSD-Dashboard-Config.ini ]; then KIND=wpsd; else KIND=pistar; fi
echo "Hotspot type: $KIND ($(hostname))"

WAS_RO=0
if [ "$KIND" = pistar ] && awk '$2=="/"{print $4}' /proc/mounts | grep -q '^ro'; then
    WAS_RO=1
    echo "Making the SD card writable for the install"
    mount -o remount,rw / 2>/dev/null || true
    mount -o remount,rw /boot 2>/dev/null || true
fi
back_to_ro() {
    if [ "$WAS_RO" = 1 ]; then
        sync
        mount -o remount,ro / 2>/dev/null || true
        mount -o remount,ro /boot 2>/dev/null || true
        echo "SD card back to read-only"
    fi
}
trap back_to_ro EXIT

tr -d '\r' < "$HERE/m5status.php" > "$WEB/m5status.php"
chown www-data:www-data "$WEB/m5status.php"
chmod 644 "$WEB/m5status.php"
echo "Installed $WEB/m5status.php"

if [ "$KIND" = wpsd ]; then
    mkdir -p "$KEEP"
    cp "$WEB/m5status.php" "$KEEP/m5status.php"
    chown -R pi-star:pi-star "$KEEP" 2>/dev/null || true
    if [ -f "$ENSURE" ]; then
        # Already set up (maybe also guarding other files, e.g. dstar_cmd.php): keep that
        # script and just refresh the keeper copy it reads from.
        echo "Self-heal script already present, keeper copy refreshed"
    else
        cat > "$ENSURE" <<'EOF'
#!/bin/bash
# Re-installs dashboard endpoint files into /var/www/dashboard if WPSD's
# SlipStream diagnostics task wipes them. Source copies live outside any
# WPSD git-managed dir (safe from the sweep). Installed by ShackDash.
SRC_DIR=/home/pi-star/dstar-web
DST_DIR=/var/www/dashboard
FILES="m5status.php"
for f in $FILES; do
  SRC="$SRC_DIR/$f"
  DST="$DST_DIR/$f"
  if [ -f "$SRC" ] && { [ ! -f "$DST" ] || ! cmp -s "$SRC" "$DST"; }; then
    cp "$SRC" "$DST"
    chown www-data:www-data "$DST"
  fi
done
EOF
        chmod 755 "$ENSURE"
        echo "Installed $ENSURE"
    fi
    cat > /etc/systemd/system/ensure-m5status.service <<'EOF'
[Unit]
Description=Ensure m5status.php dashboard endpoint is installed

[Service]
Type=oneshot
ExecStart=/home/pi-star/ensure-m5status.sh
EOF
    cat > /etc/systemd/system/ensure-m5status.timer <<'EOF'
[Unit]
Description=Periodically ensure m5status.php is installed

[Timer]
OnBootSec=30
OnUnitActiveSec=30
Unit=ensure-m5status.service

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now ensure-m5status.timer >/dev/null 2>&1
    echo "Self-heal timer: $(systemctl is-active ensure-m5status.timer)"
fi

# Self-test through the hotspot's own web server
if command -v curl >/dev/null; then
    OUT="$(curl -s -m 10 http://127.0.0.1/m5status.php || true)"
    if printf '%s' "$OUT" | grep -q '"hostname"'; then
        echo "Self-test OK: $(printf '%s' "$OUT" | head -c 160)..."
    else
        echo "WARNING: http://127.0.0.1/m5status.php did not return the expected JSON:"
        printf '%s\n' "$OUT" | head -c 400; echo
        exit 2
    fi
fi
echo "Done. Add this hotspot in ShackDash: tab O > EDIT DEVICES > type 'WPSD hotspot', host $(hostname).local"
