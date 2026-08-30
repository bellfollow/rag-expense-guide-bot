# 지시: eval/ 커밋 + README 병합 (수정 F)

## 배경 — 지적 3개 모두 맞다

1. **`eval/` 없음** — 스크립트가 이 레포에 없는데 README §13이 표로 소개한다.
   클론한 사람이 없는 파일을 찾게 된다.
2. **n8n 스테일** — 초기 프로토타입(`backup/docker-compose.yml`) 구조였고
   현재 `docker-compose.yml`엔 없다. 틀린 정보였다. **수정본에서 고쳤다.**
3. **덮어쓰기 손실** — 현재 `README.md`의 실행법(`run_demo.bat`/`stop_demo.bat`)과
   "문제 정의" 섹션이 draft에 없다. 통째로 교체하면 초심자 안내가 사라진다.

이번 작업은 **① eval/ 파일 배치 → ② README 병합** 순서다.

---

## 작업 1 — `eval/` 디렉토리 생성

첨부한 5개 파일을 레포 루트 아래 `eval/`에 그대로 배치한다.

```
eval/
├── README.md                 사용법·판정 기준
├── run_eval.py               채점기
├── variance_probe.py         분산 국소화
├── survey_all.py             미검토 사진 조사
└── labels_prefilled.csv      31장 정답 라벨
```

**파일 내용을 수정하지 마라.** 그대로 배치만 한다.

`.gitignore`에 아래를 추가한다(이미 있으면 건너뛴다).

```gitignore
# 평가용 실물 영수증 이미지 — 개인정보라 커밋하지 않는다
eval/receipts/
eval/*.jsonl
eval/*_result.md
eval/survey.md
eval/variance_probe.md
```

`labels_prefilled.csv`는 **커밋한다.** 이미지 파일명과 정답 라벨만 들어 있고
이미지 자체는 포함하지 않는다.

---

## 작업 2 — README 병합 (교체 아님)

첨부한 `README_draft.md`를 현재 `README.md`에 **병합**한다. 통째로 덮어쓰지 마라.

### 유지할 것 (현재 README에서 가져와 draft에 넣는다)

- **"문제 정의" 섹션** — draft 최상단(제목 바로 아래, "이 프로젝트에서 실제로 한 일" 앞)에 배치
- **실행법** (`run_demo.bat` / `stop_demo.bat`, Windows 원클릭) — 새 섹션으로 만들어
  **`## 12. 스택` 바로 앞**에 넣는다. 제목은 `## 12. 실행` 정도로 하고 이후 번호를 밀어라.
  초심자가 클론하고 바로 실행할 수 있어야 한다.

### 버릴 것 (draft로 대체)

- "남은 과제"의 `/review-settlement` **"구현 예정"** — 이미 구현돼 있어 틀린 정보다.
  draft §11 「한계」가 그 자리를 대신한다.
- 현재 README에 측정 수치가 있다면 draft의 것으로 교체한다(3회 반복 측정 기준).

### 판단이 필요하면

현재 README에만 있는 내용 중 위에 언급되지 않은 게 있으면 **지우지 말고 보고하라.**
내가 판단한다. 임의로 버리지 마라.

---

## 검증

1. README에서 언급하는 파일이 **전부 실재하는지** 확인한다
   (`eval/run_eval.py`, `eval/labels_prefilled.csv`, `run_demo.bat`, `stop_demo.bat` 등).
   §13 표의 경로가 실제 배치와 일치해야 한다.
2. 스택 설명이 현재 `docker-compose.yml`과 일치하는지 확인한다.
   n8n이 다시 등장하면 안 된다.
3. `python eval/run_eval.py --help`가 에러 없이 뜨는지 확인한다
   (앱 호출 없이 argparse만 도는지).
4. 문서 안의 상대 경로 링크가 깨지지 않는지 확인한다.

---

## 하지 말 것

- `eval/` 스크립트 내용을 수정하지 마라 (배치만)
- 영수증 이미지를 커밋하지 마라
- 현재 README의 내용을 임의 판단으로 삭제하지 마라 — 애매하면 보고
- 측정 수치를 임의로 바꾸거나 반올림하지 마라
- 커밋하지 마라

## 보고할 것

1. `eval/` 배치 결과 (`ls eval/`)
2. `.gitignore` 변경 diff
3. README 병합 결과 — **어떤 섹션을 어디서 가져왔고 무엇을 버렸는지** 목록
4. 현재 README에만 있어 판단이 필요한 내용이 있으면 그 원문
5. 검증 1~4 결과
