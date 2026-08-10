@echo off
REM 데모 원클릭 실행: 탐색기에서 더블클릭
cd /d "%~dp0"

echo [1/3] Docker 컨테이너 기동 중...
docker compose up -d
if errorlevel 1 (
    echo Docker 기동 실패 - Docker Desktop이 켜져있는지 확인하세요.
    pause
    exit /b 1
)

echo [2/3] 서버 준비 대기 중...
set COUNT=0
:wait
timeout /t 2 /nobreak >nul
curl -sf http://localhost:5000/health >nul 2>&1
if not errorlevel 1 goto ready
set /a COUNT+=1
if %COUNT% lss 15 goto wait
echo 서버가 30초 안에 준비되지 않음 - docker logs fastapi 로 상태 확인 필요
pause
exit /b 1

:ready
echo [3/3] 브라우저 여는 중...
start http://localhost:5000/
echo 완료.
