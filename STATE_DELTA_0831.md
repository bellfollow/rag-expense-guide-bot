# STATE_DELTA_0831 — `document/PROJECT_STATE.md`(커밋 `e934f4b`, 2026-08-31 15:26:29) 이후 변경사항

작성일: 2026-09-30. 코드/커밋은 이 작업 중 수정하지 않음. 항목 7·8은 로컬 Docker
스택(`run_demo.bat`)을 이번 세션에서 기동해 실측했다 — 자세한 내용은 각 절 참고.

---

## 1. 커밋 목록 (`git log --oneline e934f4b..HEAD`)

12개 커밋, 전부 배포/UI/정리 작업. 판정 로직(추출·분류·컴플라이언스) 변경 없음.

| 커밋 | 요약 |
|---|---|
| 73ca4f6 | docs: README 재작성 — 목표 워크플로우, 측정 결과, 원인 규명 서사 |
| 30acda8 | feat(ui): 3-tier 목업 + 규정집 관리 화면 |
| daf2418 | chore: MongoDB 제거 — 코드에서 사용되지 않음 |
| a48b0a4 | chore: 검증 스크립트를 eval/로 이동 |
| 578fe8d | docs: 변환 검증 섹션 추가 |
| 82b3476 | docs: 화면 스크린샷 4장 추가 |
| f888523 | build: 배포 가능한 이미지로 수정 |
| c156b5d | build: Render 배포용 PORT 환경변수 대응 |
| d00ad7b | chore: Qdrant 로컬 인덱스 커밋 — 배포 이미지 빌드에 필요 |
| 922ad8d | 배포를 위한 Qdrant 추가, 프롬프트 폴더 삭제 |
| 431bfd5 | fix: Dockerfile에 qdrant_data COPY 추가 |
| eb123d5 | docs: 배포 정보 추가 |

(출처: `git log --oneline e934f4b..HEAD`, 이번 세션 실행)

---

## 2. 변경 파일 목록 (`git diff --stat e934f4b..HEAD`)

18개 파일, +917/-684줄.

| 파일 | 변경 |
|---|---|
| `README.md` | 410줄 순감소 (재작성) |
| `static/index.html` | +1006/구조 전면 변경 (3-tier UI 목업) |
| `docker-compose.yml` | mongodb 서비스 제거, 14줄 변경 |
| `Dockerfile.fastapi` | multi-stage 전환, 21줄 변경 |
| `config.py` | +6/-2 (QDRANT_PATH local mode 분기 추가) |
| `.gitignore` | +9/-0 |
| `.env.example` | +4/-0 |
| `scripts/migrate_to_local_qdrant.py` | 신규, +75 |
| `scripts/verify_local_qdrant.py` | 신규, +54 |
| `qdrant_data/meta.json`, `qdrant_data/.lock`, `qdrant_data/collection/documents/storage.sqlite` | 신규 (로컬 인덱스 커밋, 5,894,144 bytes) |
| `docs/images/*.png` 4장 | 신규 (스크린샷) |
| `test_impact.py → eval/test_impact.py` | 이동 (rename, 0줄 diff) |
| `validate_conversion.py → eval/validate_conversion.py` | 이동 (rename, 0줄 diff) |

(출처: `git diff --stat e934f4b..HEAD`, 이번 세션 실행)

---

## 3. `docker-compose.yml` 서비스 / `Dockerfile.fastapi` COPY 대상

**`docker-compose.yml`** (현재): `qdrant`(포트 6333, 서버 모드) + `fastapi`(포트 5000, `--reload`, 소스 바인드마운트) — `mongodb` 서비스는 `daf2418`에서 제거됨 (출처: `git diff e934f4b..HEAD -- docker-compose.yml`, 이번 세션 확인).

**`Dockerfile.fastapi`** COPY 대상 (multi-stage, `922ad8d`/`431bfd5`에서 확정):
```
COPY app.py config.py chunking.py embeddings.py pipeline.py ./
COPY static ./static
COPY qdrant_data ./qdrant_data
```
`e934f4b` 시점에는 `COPY app.py .` 한 줄뿐이었다(`config.py` 등 미포함 — 컴포즈의 바인드마운트에 의존해야 이미지가 동작하는 상태). 이후 `431bfd5`에서 `qdrant_data` COPY가 추가되며 현재 형태로 확정됨. (출처: `git diff e934f4b..HEAD -- Dockerfile.fastapi`)

---

## 4. `eval/` 08-31 이후 결과 파일

**없음.** `eval/` 디렉토리의 가장 최신 결과 파일은 `eval/h3split_regression_run1.md`(mtime 2026-08-31 14:50:50)이며, `e934f4b` 커밋 시각(2026-08-31 15:26:29)보다도 이르다. `git log --oneline e934f4b..HEAD -- eval/`는 `a48b0a4`(파일 이동, 0줄 diff) 한 건만 나온다 — 즉 **08-31 이후 새로운 측정은 없었다.** (출처: `ls --time-style=full-iso -la eval/*.md eval/*.jsonl eval/*.csv`, `git log --oneline e934f4b..HEAD -- eval/`, 이번 세션 실행)

---

## 5. README.md 현재 목차 / §11

```
# 사업비 집행 가이드 챗봇
## 1. 뭘 하는가
## 2. 목표 워크플로우
## 3. 측정 결과
## 4. 어떻게 여기까지 왔나
## 5. 변환 검증
## 6. 알려진 한계
## 7. 스택 / 실행법
```
(출처: `grep -n "^#\|^##" README.md`, 전체 143줄, 이번 세션 확인)

**§11은 존재하지 않는다.** 섹션은 1~7뿐이다. 지난 조사(`PROJECT_STATE_draft.md` 작성 시)에서도 같은 결과였고 이번에도 동일 — README 구조 자체가 그 사이 안 바뀌었다(`73ca4f6`이 마지막 README 커밋, `e934f4b` 이전). "§11"을 지시한 근거가 다른 문서(예: 로컬 미커밋 문서)라면 확인이 필요하다.

---

## 6. config.py LLM / embedding 모델명

`e934f4b` 이후 `config.py` diff는 `QDRANT_PATH` 분기 추가뿐, 모델명 변경 없음(출처: `git diff e934f4b..HEAD -- config.py`).

| 용도 | 모델 | 위치 |
|---|---|---|
| PDF 변환 / 영수증 추출 / 분류 / 컴플라이언스 / 문서 매칭 / 문서 tier | `gemini-3.5-flash-lite` | `config.py:14,46,81,288,332,366` |
| chat | `gemini-3.1-flash-lite-preview` | `config.py:31` |
| 임베딩 | `jina-embeddings-v3` (1024-dim) | `embeddings.py:11`, `config.py:9` |

---

## 7. `national_eval_rule.pdf` 청크 길이 분포 — Qdrant 실측 (1회, 2026-09-30)

로컬 Docker 스택(`docker compose up -d`, `qdrant`+`fastapi` 컨테이너)을 이번 세션에서 기동해 Qdrant에 직접 scroll 쿼리를 날려 측정했다. 전체 컬렉션 466 포인트 = `national_eval_rule.pdf` 431 + `guiideline.pdf` 35 (`466`는 README.md:131의 "466포인트" 서술과 일치 확인).

| 지표 | 값 |
|---|---|
| 청크 수 | 431 |
| min | 53자 |
| median | 1026자 |
| mean | 945.7자 |
| max | 2143자 |
| 8000자 초과 | **0건** |

(출처: `POST http://localhost:6333/collections/documents/points/scroll`, filter `source_file=national_eval_rule.pdf`, payload 필드 `content`의 문자열 길이, 이번 세션 실행. **(1회)** — 반복 측정 대상이 아닌 정적 데이터라 반복 무의미하나, 규칙상 표기.)

---

## 8. `/chat` no_answer 4문항 실호출 — **실패**

`eval/labels_chat.csv`의 no_answer 4문항(n01~n04)을 로컬 스택의 `/chat`에 실제로 호출했다(컨테이너 내부 Python `requests` 사용 — bash curl 한글 인코딩 문제 회피). **4건 모두 HTTP 500, Gemini API 429 응답으로 실패**:

```
429 Your prepayment credits are depleted. Please go to AI Studio at
https://ai.studio/projects to manage your project and billing.
```

| id | question | 결과 |
|---|---|---|
| n01 | 해외 학회 갈 때 비행기값도 나오나요? | 500 — quota 소진 |
| n02 | 저희 팀원 월급도 여기서 받을 수 있나요? | 500 — quota 소진 |
| n03 | 논문 게재료도 문헌구입비로 인정되나요? | 500 — quota 소진 |
| n04 | 졸업논문 심사비도 창업탐색비로 처리 가능한가요? | 500 — quota 소진 |

(출처: `docker exec fastapi python /tmp/call_chat.py`, `POST /chat` form-data `query=...`, 이번 세션 2026-09-30 실행. 응답 원문 4건 전부 동일 오류 메시지.)

**→ 응답 원문 확보 불가.** 현재 `.env`에 설정된 `GEMINI_API_KEY`의 결제 크레딧이 소진돼 있어, `/chat`뿐 아니라 Gemini를 호출하는 모든 엔드포인트(`/classify-receipt` 등)가 같은 오류로 실패할 것으로 추정된다(코드상 모든 LLM 호출이 동일 `GEMINI_CONFIG`/API 키를 공유 — `config.py`). **라이브 데모(`README.md:3`의 Render 링크)도 같은 키를 쓴다면 현재 서비스 불가 상태일 가능성이 있다** — 별도 확인 필요.

---

## 완료

- README §11 재확인: 존재하지 않음(섹션 1~7). §6 "알려진 한계"가 가장 근접.
- config.py 모델명: `e934f4b` 이후 변경 없음.
- Qdrant 청크 길이 분포 실측: `national_eval_rule.pdf` 431개, 8000자 초과 0건 — 청크 크기 관련 우려 없음.

## 열린 문제 (우선순위)

**P0 — 즉시 확인 필요**
1. **Gemini API 크레딧 소진** — `/chat` 4건 전부 500 (§8). 라이브 데모 및 로컬 스택의 모든 LLM 경로가 동작하지 않을 가능성. `document/PROJECT_STATE.md`나 이전 `PROJECT_STATE_draft.md`의 측정치는 이 문제가 생기기 전(08-31) 값이라 현재도 재현된다는 보장이 없다.
2. **eval/ 측정 정지 상태** — 08-31 15:26(`e934f4b`) 이후 한 달간(~09-30) 판정 로직에 대한 재측정이 전혀 없다. 그 사이 배포 관련 변경(Dockerfile, docker-compose, QDRANT_PATH 분기)이 실제 판정 파이프라인에 영향 없는지 회귀 검증되지 않았다.

**P1**
3. `Dockerfile.fastapi`가 `e934f4b` 시점엔 `app.py`만 COPY해 이미지 단독 실행이 불가능했던 상태였다 — `431bfd5`에서 수정됨. 과거 상태이므로 현재는 해소됐지만, 배포 이미지를 `docker build`만으로 검증하지 않고 `docker compose`(바인드마운트로 결함을 가려줌)로만 테스트하면 같은 패턴이 재발할 수 있다.

---

## 문서 불일치

1. **README §11 미존재** — 사용자 요청("README.md §11 원문")과 실제 파일(1~7절)이 불일치. 반복 확인됨.
2. **인덱스 포인트 수는 일치, 용량 표기는 불일치**: README.md:131 "466포인트, 20MB" 중 포인트 수(466)는 이번 실측(§7)과 정확히 일치하나, 20MB는 실제 `storage.sqlite` 5,894,144 bytes(≈5.6MB)와 3.5배 차이 — 이전 조사(`PROJECT_STATE_draft.md`)에서 지적한 것과 동일한 불일치가 이번 실측으로도 재확인됨.

---

## 하지 말 것

- **bash curl로 한글 쿼리 테스트 금지** — 이번에도 `/chat` 호출은 컨테이너 내부 Python `requests`로 수행했다(메모리 `feedback_korean_curl_encoding` 규칙 적용).
- **이 문서의 §7·§8 수치를 "재현됨"으로 오해하지 말 것** — §7은 정적 데이터 조회라 안정적이지만, §8은 API 키 크레딧 상태에 종속적인 결과다. 크레딧 충전 후 재호출하면 다른 결과가 나올 수 있다.

---

## 측정 방법

- §7: Qdrant REST API `points/scroll`을 `source_file` 필터로 직접 호출, payload의 `content` 필드 길이를 Python으로 집계. 정적 데이터 조회이므로 반복 측정 불필요.
- §8: 컨테이너 내부에 Python 스크립트를 복사해 `requests.post("http://localhost:5000/chat", ...)`로 4문항 순차 호출, 응답 JSON을 그대로 저장 후 읽음. 실패 시에도 원문 오류 메시지를 그대로 인용했다(가공하지 않음).
- 이번 세션에서 로컬 Docker 스택(`qdrant`+`fastapi`)을 새로 기동했다 — 작업 종료 후에도 계속 떠 있는 상태다. 필요 시 `stop_demo.bat` 또는 `docker compose down`으로 종료할 것.
