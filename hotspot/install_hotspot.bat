@echo off
rem Double-click to install m5status.php on your hotspot(s) for ShackDash's MY SHACK tab.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_hotspot.ps1" %*
pause
