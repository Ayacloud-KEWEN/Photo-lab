@echo off
rem Double-click to start LUMEN Studio (builds it first if needed).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" %*
if errorlevel 1 (
  echo.
  echo LUMEN Studio could not be started. See the messages above.
  pause
)
