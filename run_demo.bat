@echo off
REM One-click demo launcher: double-click in Explorer
cd /d "%~dp0"

echo [0/4] Checking Docker daemon...
docker info >nul 2>&1
if not errorlevel 1 goto dockerready

echo Docker Desktop is not running - starting it...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set COUNT=0
:waitdocker
ping -n 4 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 goto dockerready
set /a COUNT+=1
if %COUNT% lss 40 goto waitdocker
echo Docker Desktop did not become ready within 120 seconds.
pause
exit /b 1

:dockerready
echo [1/4] Starting Docker containers...
docker compose up -d
if errorlevel 1 (
    echo Failed to start containers - check that Docker Desktop is running.
    pause
    exit /b 1
)

echo [2/4] Waiting for server to be ready...
set COUNT=0
:wait
ping -n 3 127.0.0.1 >nul
curl -sf http://localhost:5000/health >nul 2>&1
if not errorlevel 1 goto ready
set /a COUNT+=1
if %COUNT% lss 15 goto wait
echo Server not ready after 30 seconds - check status with: docker logs fastapi
pause
exit /b 1

:ready
echo [3/4] Opening browser...
start http://localhost:5000/
echo [4/4] Done.
