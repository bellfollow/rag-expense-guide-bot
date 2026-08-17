@echo off
REM Full shutdown: stop containers + quit Docker Desktop + force-kill WSL (reclaims VmmemWSL memory)
REM "wsl --shutdown" alone sometimes fails to release VmmemWSL, so we also force-stop WslService.
REM Requires admin rights - will self-elevate via UAC prompt if not already elevated.
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Admin rights required - relaunching elevated...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo [1/4] Stopping containers...
docker compose down

echo [2/4] Quitting Docker Desktop...
taskkill /IM "Docker Desktop.exe" /F >nul 2>&1
powershell -NoProfile -Command "Get-Process 'com.docker.*' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"

echo [3/4] Attempting graceful WSL shutdown...
wsl --shutdown >nul 2>&1

echo [4/4] Force-stopping WSL service (reclaims VmmemWSL memory)...
powershell -NoProfile -Command "Stop-Service -Name 'WslService' -Force -ErrorAction SilentlyContinue"

echo Done - VmmemWSL memory reclaimed.
pause
