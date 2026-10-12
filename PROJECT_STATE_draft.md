# PROJECT_STATE (초안) — 2026-09-30 작성, 레포 상태 기준일 2026-09-08

> 이 파일은 `document/PROJECT_STATE.md`(2026-08-31자, 커밋 `e934f4b` 기준 — 현재 정본)를 대체하지 않는다.
> 그 이후 `ed1488f..HEAD` 구간(배포 작업 14커밋)을 반영한 갱신 초안이며, 검토 후 정본에 병합할지 판단할 것.
> 코드/커밋은 이 작업 중 수정하지 않았다.

---

## 현재 상태

- HEAD: `eb123d5` (2026-09-08), branch `main`, working tree clean.
- `document/PROJECT_STATE.md`가 정본으로 지정한 커밋(`e934f4b`, 2026-08-31) 이후 **14개 커밋**이 더 쌓였다 — 전부 배포 작업. 측정치(receipt/chat) 갱신 커밋은 없다.
- 이번 구간(`ed1488f..HEAD`, 출처: `git log --oneline ed1488f..HEAD`)의 흐름: (1) 영수증 판정 로직 수정 3건 → (2) README 재작성 → (3) UI 목업 → (4) MongoDB 제거 → (5) 검증 스크립트 이동 → (6) Render 배포 대응 6커밋.

| 커밋 | 날짜 | 한 줄 요약 |
|---|---|---|
| 27bd063 | 09-08(주: 원 커밋일 08-31) | is_receipt 거절 경로, status 게이트 수정, 검색 쿼리 고정 |
| e934f4b | 08-31 | feat(chunking): split guiideline.pdf at h3 boundaries |
| 73ca4f6 | 08-31 | docs: README 재작성 |
| 30acda8 | 09-07 | feat(ui): 3-tier 목업 + 규정집 관리 화면 |
| daf2418 | 09-07 | chore: MongoDB 제거 — 코드에서 사용되지 않음 |
| a48b0a4 | 09-07 | chore: 검증 스크립트를 eval/로 이동 |
| 578fe8d | 09-07 | docs: 변환 검증 섹션 추가 |
| 82b3476 | 09-07 | docs: 화면 스크린샷 4장 추가 |
| f888523 | 09-07 | build: 배포 가능한 이미지로 수정 |
| c156b5d | 09-08 | build: Render 배포용 PORT 환경변수 대응 |
| d00ad7b | 09-08 | chore: Qdrant 로컬 인덱스 커밋 |
| 922ad8d | 09-08 | 배포를 위한 Qdrant 추가, 프롬프트 폴더 삭제 |
| 431bfd5 | 09-08 | fix: Dockerfile에 qdrant_data COPY 추가 |
| eb123d5 | 09-08 | docs: 배포 정보 추가 |

(출처: `git log --format="%h %ad %s" --date=short ed1488f..HEAD`. 날짜 열 첫 줄은 커밋 로그상 09-08로 찍혀 있으나 내용상 08-31 작업 — author date/commit date 불일치 가능성, 미확인.)

---

## 스택

(출처: `config.py`, `embeddings.py`, `docker-compose.yml`, `Dockerfile.fastapi`)

- **API 서버**: FastAPI (`app.py`, 471줄)
- **벡터 DB**: Qdrant — 로컬 개발은 `docker-compose.yml`의 별도 `qdrant` 컨테이너(포트 6333), 배포 이미지는 `qdrant-client` local mode(파일 기반, `qdrant_data/`를 이미지에 `COPY`) — **두 경로가 서로 다른 Qdrant 아키텍처를 쓴다** (상세는 아래 "문서 불일치" 참고)
- **LLM (변환/추출/분류/컴플라이언스)**: `gemini-3.5-flash-lite` — `config.py:14,46,81,288,332,366`의 `GEMINI_CONVERT_MODEL`/`GEMINI_RECEIPT_EXTRACT_MODEL`/`GEMINI_DOC_TIER_MODEL`/`GEMINI_RECEIPT_CLASSIFY_MODEL`/`GEMINI_RECEIPT_COMPLIANCE_MODEL`/`GEMINI_DOC_MATCH_MODEL` 전부 동일 모델
- **LLM (chat)**: `gemini-3.1-flash-lite-preview` — `config.py:31`의 `GEMINI_CHAT_MODEL`만 다른 모델 사용
- **임베딩**: `jina-embeddings-v3`, 1024-dim — `embeddings.py:11`, `config.py:9`
- **컨테이너**: Docker Compose(로컬), `Dockerfile.fastapi`(배포, multi-stage)
- MongoDB는 제거됨 (`daf2418`) — `mongodb_data/`는 로컬에 남아 있으나 `.gitignore:4`로 무시됨

---

## 측정 수치

**모든 수치는 실제 영수증/질문 데이터 기반. 규칙: 3회 반복 최솟값 기준으로만 채택 판정(`eval/README.md:52-56`). 3회 세트가 아닌 파일은 "(1회)" 표기.**

### 영수증 판정(`/classify-receipt`) — 최신 3회 세트: `eval/queryfix_run{1,2,3}.md` (2026-08-31 10:04~11:08)

| 항목 | run1 | run2 | run3 | 출처 |
|---|---|---|---|---|
| flag macro recall | 100% | 100% | 100% | `eval/queryfix_run1.md:10`, `run2.md:10`, `run3.md:10` |
| status (compliance) | 100%(31/31) | 97%(30/31) | 97%(30/31) | 위 파일 각 11행 |
| 금액 추출 | 94%(29/31) | 94% | 94% | 위 파일 각 7행 |
| 날짜 추출 | 100%(31/31) | 100% | 97%(30/31) | 위 파일 각 8행 |
| 비목(sub_item) 분류 | 68%(21/31) | 65%(20/31) | 65% | 위 파일 각 9행 |
| citation 게이트 차단 | 0건 | 0건 | 0건 | 위 파일 각 "게이트 차단" 절 |

→ status 97~100%, 다수결 베이스라인 90% (베이스라인 값 출처: `eval/queryfix_run1.md:17` 등 "다수결 베이스라인 90%" 문구). **분산 0%p라는 표현은 이 3회 세트의 flag 지표에만 해당** — status/비목은 이 세트 안에서도 0~3%p 흔들린다.

citation 정답 조항 인용 **9/9**(r001/r002/r004 × 3회) — 출처: `document/FINDINGS_2026-08-31_citation_grounding.md:71`("citation 정답 조항 인용 9/9(3회)"). 수정 전 0/18은 같은 문서 17-21행("18건 전수... L248/L258 인용 0건").

### 영수증 판정 — 최신 회귀 확인: `eval/h3split_regression_run1.md` (2026-08-31 14:50) **(1회)**

flag 100%(31/31), status 100%(31/31), 금액 94%(29/31), 날짜 100%(31/31), 비목 65%(20/31). h3 청킹 변경(`e934f4b`) 후 영수증 판정이 깨지지 않았는지 확인한 단발 회귀 테스트로, 3회 세트가 아니다.

### `is_receipt` 거절 — `eval/nonreceipt_run{1,2,3}.md` (2026-08-30, 3회)

negative recall **100%(37/37)** 3회 모두 동일 (출처: 각 파일 3행). 오탐(실영수증 거절) 0/93 — 이 수치의 산출 근거 파일은 이번 조사에서 직접 열람하지 못함, `document/PROJECT_STATE.md:35` 인용.

### chat retrieval(`/search`) — 최신: `eval/chat_h3split_run1.md` (2026-08-31 14:44) **(1회 파일)**

| 지표 | 전체(20건) | colloquial(10건) | formal(10건) |
|---|---|---|---|
| hit@1 | 65%(13/20) | 60%(6/10) | 70%(7/10) |
| hit@5 | 85%(17/20) | 80%(8/10) | 90%(9/10) |
| MRR | 0.758 | 0.700 | 0.817 |

(출처: `eval/chat_h3split_run1.md:7-31`)

**1회지만 판단 근거 있음**: `eval/chat_baseline_run{1,2,3}.jsonl` 3개 파일을 직접 diff한 결과 0바이트 차이 확인(`diff eval/chat_baseline_run1.jsonl eval/chat_baseline_run2.jsonl` 및 run3 모두 0줄, 이번 세션에서 재실행 검증) — `/search`가 임베딩+코사인 검색만 타는 결정론적 경로라는 README 주장(`README.md:62`)이 사실로 확인됨. h3split 이후 결과도 같은 경로이므로 1회로 충분하다는 논리이나, **h3split 자체에 대해 3회 반복 검증은 없었다.**

개선 전 baseline: `eval/chat_baseline_run1.md` — hit@1 55%(11/20), colloquial 40%(4/10), formal 70%(7/10), MRR 0.639.

`MIN_CHUNK_SIZE` 300→100 변경 no-op 확인: `eval/chat_minfix_run1.md`의 hit@k 집계치가 baseline과 전부 동일. jsonl 원본은 48줄 차이 있음(`diff eval/chat_baseline_run1.jsonl eval/chat_minfix_run1.jsonl` = 48, 이번 세션 재확인) — score 소수점 자리 수준의 임베딩 API 미세 변동이며, hit@k/순위 집계는 불변.

no_answer 판별 불가: answerable 20건 top1 평균 0.5065 vs no_answer 4건 평균 0.4627 (`eval/chat_h3split_run1.md:72-73`) — 거의 갈리지 않음.

---

## 완료

- 영수증 flag 판정: macro recall 100% (3회, `eval/queryfix_run*.md`)
- citation 근거 정합성: 9/9 (3회, `document/FINDINGS_2026-08-31_citation_grounding.md`)
- `is_receipt` 거절: negative recall 100% (37장×3회), 오탐 0/93
- chat retrieval: hit@1 65% (colloquial 60%/formal 70%), 개선 전 55% 대비 +10%p — 단, h3split 이후 값은 1회만 측정
- TODO/FIXME/XXX 마커: `*.py` 전체에서 0건 (`grep -rn "TODO\|FIXME\|XXX" --include=*.py .`, 이번 세션 재확인)
- MongoDB 제거 완료 (`daf2418`)
- 검증 스크립트 `eval/`로 이동 (`a48b0a4`)
- Render 배포: 단일 컨테이너, 이미지 크기 1.25GB→784MB(멀티스테이지)→795MB(인덱스 포함), 런타임 메모리 125MB (출처: `README.md:129-137`, 이번 세션에서 재측정하지 않음 — README 서술 인용)

---

## 열린 문제 (우선순위)

**P0 — 신뢰성/보안**
1. 관리자/사용자 인증 없음 (`README.md:43`)
2. 영수증 평가셋 31장 중 `지원불가` 정답 3건뿐 — 1건이 33%p. 금지 목록에 유류비·주차비를 명시했는데 정답 3건이 정확히 그것이라 leakage에 가깝다 (`README.md:106`)

**P1 — 미측정 기능**
3. `/review-settlement` 미측정, UI 미노출 (`README.md:45,110`)
4. `absolute_cap`(절대금액 캡) 코드는 있으나 소비하는 곳이 없어 구조적으로 미작동 (`README.md:111`)

**P2 — 커버리지 공백**
5. `/chat` 답변 품질 미측정 — retrieval만 측정됨 (`README.md:108`)
6. score로 no_answer 판별 불가 — 위 "측정 수치" 참고 (`README.md:109`, `eval/chat_h3split_run1.md:72-73`)
7. 렌터카·범용기자재·귀금속 조항 검증 0건 (해당 영수증이 평가셋에 없음, `README.md:107`)

**P3 — 범위 밖**
8. HWP 지원 없음 — PDF만 변환 (`README.md:42`)
9. "항목이 맞는 자리에 들어갔나"(정산서류 내 비목 배치 검증) 미착수 (`README.md:44`)

> 참고: README에는 §11이 없다(전체 7개 섹션). 사용자가 지정한 "§11 열린 문제"에 해당하는 내용은 **§6 "알려진 한계"**로 판단해 위 내용을 그대로 인용했다 — 섹션 번호가 다른 문서를 가리키고 있었다면 확인 필요.

---

## 문서 불일치 (README vs compose vs 코드)

1. **커밋 메시지 vs 실제 diff**: `922ad8d` 커밋 메시지는 "프롬프트 폴더 삭제"라 하지만, `git show --stat 922ad8d`에는 `prompt/` 관련 파일 변경이 전혀 없다. 실제로 `git ls-files`에서 `prompt/*.md` 6개 파일이 현재도 추적 중이다(`.gitignore`엔 `prompt/`가 등록돼 있으나 이미 추적 중인 파일에는 효과 없음). 커밋 메시지와 실제 상태가 다르다.
2. **인덱스 용량**: `README.md:131`은 "인덱스(466포인트, 20MB)"라 적었으나, 실측 `qdrant_data/collection/documents/storage.sqlite`는 5,894,144 bytes(≈5.6MB, `922ad8d` diff stat과 현재 `du -sh qdrant_data` = 5.7M 둘 다 동일) — 약 3.5배 차이. 포인트 수(466)는 이번 조사에서 검증하지 못함(Qdrant 구동 필요).
3. **Qdrant 아키텍처 이원화**: `docker-compose.yml`은 별도 `qdrant` 컨테이너(서버 모드, 포트 6333)를 띄우는 로컬 개발 구성이고, `Dockerfile.fastapi`는 `qdrant_data/`를 이미지에 구워 넣는 local-mode(파일 기반) 구성이다. 같은 리포에 두 개의 서로 다른 Qdrant 운영 방식이 공존하는데, `docker-compose.yml`에는 이 구분이 문서화돼 있지 않다.
4. **루트에 남은 빈 디렉토리**: 레포 루트에 `validate_conversion.py/`라는 빈 디렉토리가 있다(파일이 아니라 디렉토리, git 미추적). `a48b0a4`("검증 스크립트를 eval/로 이동") 이후 남은 잔재로 추정 — 실제 스크립트는 `eval/validate_conversion.py`에 있다.

---

## 하지 말 것

- **bash curl로 한국어 쿼리 테스트 금지.** Windows 환경에서 인코딩이 깨져 서버에 도달하는 문자열이 손상된다. 이걸 "인덱싱 문제"로 오진한 전례가 있다 — Python `requests`로 테스트할 것. (출처: `README.md:76`, `document/FINDINGS_2026-08-31_citation_grounding.md:26-32`)
- **1회 측정으로 채택/롤백 판단 금지.** 코드를 안 바꾸고 3회 돌렸을 때 macro recall이 48~82%(34%p)로 흔들린 전례가 있다. 3회 반복 최솟값 기준으로만 판정한다. (출처: `eval/README.md:52-59`)
- **상수 이름만 보고 원인 추정 금지.** `MIN_CHUNK_SIZE`를 원인으로 지목해 300→100으로 낮췄지만 청크 패킹 조건이 OR라 `MAX_CHUNK_SIZE`가 실질 결정권을 쥐고 있었다 — no-op이었다. 조건문을 직접 읽을 것. (출처: `README.md:76`)
- **`survey_all.py`의 모델 출력을 정답 라벨로 쓰지 말 것.** 후보 선별용이며, 라벨로 쓰면 시스템이 자기 답을 채점하는 순환이 된다. (출처: `eval/README.md:72-73`)
- **`HANDOFF.md`를 레포 상태의 근거로 인용하지 말 것.** 세션마다 덮어써지는 휘발성 로그다. `document/PROJECT_STATE.md`가 정본. (출처: `document/PROJECT_STATE.md:4-7`)

---

## 측정 방법

(출처: `eval/README.md`)

1. 단일 클래스 수렴 검사부터 본다 — 모델 출력 종류가 1개면 정확도가 높아도 성능이 아니라 붕괴다.
2. macro recall로 판정한다 — 클래스 불균형(확인필요 28 vs 지원불가 3)에 눌리지 않는 값.
3. 클래스별 재현율로 어느 클래스를 놓치는지 본다.
4. override 게이트 발동/차단 건수를 확인한다 — 분류가 맞춘 것과 컴플라이언스가 구제한 것을 분리.
5. 판정 근거(citation)를 직접 연다 — 집계값이 같아도 근거 구성이 다를 수 있다(citation 9/9 vs 0/18 사례).
6. 채택 조건: **3회 반복 중 최솟값 > 이전 3회 최댓값**. 1회 측정으로 개선/악화 판단하지 않는다.
7. 결정론적 경로(`/search`, 임베딩+코사인만 탐)는 예외적으로 1회 측정이 허용되나, 그 근거(3회 diff 0바이트)를 먼저 실측 확인해야 한다.
