#!/bin/bash
# 데모 원클릭 실행: 컨테이너 기동 -> 헬스체크 대기 -> 브라우저 자동 오픈
set -e
cd "$(dirname "$0")"

echo "[1/3] Docker 컨테이너 기동 중..."
docker compose up -d

echo "[2/3] 서버 준비 대기 중..."
READY=0
for i in $(seq 1 30); do
    if curl -sf http://localhost:5000/health > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 2
done

if [ "$READY" -ne 1 ]; then
    echo "서버가 30초 안에 준비되지 않음 — docker logs fastapi 로 상태 확인 필요"
    exit 1
fi

echo "[3/3] 브라우저 여는 중..."
URL="http://localhost:5000/"
if command -v xdg-open > /dev/null 2>&1; then
    xdg-open "$URL"
elif command -v open > /dev/null 2>&1; then
    open "$URL"
elif command -v powershell.exe > /dev/null 2>&1; then
    powershell.exe -c "Start-Process '$URL'" > /dev/null 2>&1
else
    echo "브라우저에서 직접 열어주세요: $URL"
fi

echo "완료. $URL"
