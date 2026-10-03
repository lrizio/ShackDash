# Installs m5status.php on one or more WPSD / Pi-Star hotspots over SSH, so they show up
# in ShackDash's MY SHACK tab. Uses Windows' built-in OpenSSH (ssh / scp).
#
#   .\install_hotspot.ps1 pi-star.local
#   .\install_hotspot.ps1 192.168.1.50, dmr.local -User pi-star
#
# Without key login you are asked for the hotspot password two or three times per hotspot
# (copy, log in, and on Pi-Star sometimes sudo). The factory password is "raspberry".
param(
    [Parameter(Position = 0)][string[]]$Hotspot,
    [string]$User = "pi-star"
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
foreach ($f in "m5status.php", "install_m5status.sh") {
    if (-not (Test-Path (Join-Path $here $f))) { Write-Host "Missing $f next to this script." -ForegroundColor Red; exit 1 }
}
foreach ($exe in "ssh", "scp") {
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
        Write-Host "$exe not found. Turn on Windows' OpenSSH Client: Settings > System > Optional features." -ForegroundColor Red
        exit 1
    }
}

if (-not $Hotspot) {
    $answer = Read-Host "Hotspot name(s) or IP address(es), comma separated (e.g. pi-star.local)"
    $Hotspot = $answer -split "[,\s]+" | Where-Object { $_ }
}
if (-not $Hotspot) { exit 1 }

$failed = @()
foreach ($h in $Hotspot) {
    Write-Host ""
    Write-Host "=== $h ===" -ForegroundColor Cyan
    $target = "$User@$h"
    $opts = @("-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new")

    # Pi-Star's card is read-only, but /tmp is a RAM disk there, so copying to it is fine.
    & scp @opts (Join-Path $here "m5status.php") (Join-Path $here "install_m5status.sh") "${target}:/tmp/"
    if ($LASTEXITCODE -ne 0) { Write-Host "Copy to $h failed." -ForegroundColor Red; $failed += $h; continue }

    & ssh @opts -t $target "sed -i 's/\r`$//' /tmp/install_m5status.sh && cd /tmp && sudo bash install_m5status.sh; rc=`$?; rm -f /tmp/install_m5status.sh /tmp/m5status.php; exit `$rc"
    if ($LASTEXITCODE -ne 0) { Write-Host "Install on $h failed (exit $LASTEXITCODE)." -ForegroundColor Red; $failed += $h; continue }

    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://$h/m5status.php"
        if ($r.Content -match '"hostname"') { Write-Host "Checked from this PC: http://$h/m5status.php answers." -ForegroundColor Green }
    } catch {
        Write-Host "Installed, but this PC could not open http://$h/m5status.php ($($_.Exception.Message))." -ForegroundColor Yellow
    }
}

Write-Host ""
if ($failed) { Write-Host "Failed: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "All done. In ShackDash: tab O > EDIT DEVICES > ADD, type 'WPSD hotspot', host as above." -ForegroundColor Green
