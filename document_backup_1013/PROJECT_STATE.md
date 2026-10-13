# PROJECT_STATE — 2026-10-13

> 이 문서가 프로젝트 상태의 **정본**이다.
> 레포 루트 `HANDOFF.md`는 Claude Code가 세션마다 자동 재생성하는 **휘발성 세션 로그**로,
> `doc-folders.md` 규칙상 "매번 덮어씀 · 레포 상태 근거로 인용 금지"다.
> 그 문서의 "Known Issues: None"은 *그 세션에 블로커가 없었다*는 뜻이지
> 프로젝트에 열린 문제가 없다는 뜻이 아니다. 수정하려 하지 마라 — 다음 세션에 덮어써진다.

## 현재 상태

레포 `bellfollow/rag-expense-guide-bot`, HEAD `e63c93e` (2026-10-13).
기준 커밋 `e934f4b`(08-31) 이후 21커밋: 배포/UI/정리 12커밋(`73ca4f6`~`eb123d5`) + README 서식 1(`0b2ecbf`)
+ merge 1(`b23773d`) + REVIEW 대응 수정 7커밋(`f05a14f`~`e63c93e`). 근거: `git log e934f4b..HEAD`.
**08-31 이후 판정 로직 재측정은 없다.** 아래 측정치는 08-31 값이고, 수정 후 재채점한 값은 해당 행에 따로 표기했다.

### 기능별 측정 현황

이 프로젝트는 기능이 셋이다. 지금까지 (b)만 측정돼 있었다.

| 기능 | 엔드포인트 | 상태 |
|---|---|---|
| (a) 가이드라인 Q&A | `/chat` | retrieval 측정됨 — hit@1 65%, 답변 품질 미측정 |
| (b) 영수증 검증 | `/classify-receipt` | 측정됨 — macro 100%, citation 3/3 |
| (c) 서류 검토 | `/review-settlement` | 미측정 — 08-19 실행 1회, UI 미노출 |

**`is_receipt` 거절 경로와 `status`/`flag` 불일치를 해소했다.
비영수증 37장을 3회 모두 거절하고, `status`가 다수결 베이스라인을 처음으로 넘었다.**

| | 값 |
|---|---|
| macro recall (flag) | 100% (3회 모두) |
| 지원불가 recall | 3/3 |
| 확인필요 recall | 28/28 |
| 과신율 | 0% |
| 금액 / 날짜 추출 | 94% / 97~100% |
| `status` (compliance) | **97~100% (3회) — 베이스라인 90%, 순이득 +6~10%p** |
| `is_receipt` negative recall | **100% (37/37, 3회 모두)** |
| `is_receipt` 오탐 (실영수증 거절) | **0 / 93** — queryfix_run1~3 93행 재집계(`is_receipt==False` 0건, error 0건). **아래 주석 참고** |
| citation 정답 조항 인용 | **러너 채점 P 9/9 / F 7/9 (queryfix_run1~3), 독립 표본 3건** (`c05388c`). 쿼리 고정 전 receipt·gatefix 6개 run은 P·F 모두 0/18 |
| 비목 분류 | 65~68% — 라벨 어휘 수정 후 10개 jsonl 재채점(`18cfa3c`). 기존 "71%"는 현재 jsonl로 재현되지 않아 삭제 |
| chat retrieval hit@1 | 65% (colloquial 60% / formal 70%) |
| chat MRR | 0.758 |
| chat 미포함 | 2 / 20 |
| chat 답변 품질 | 미측정 — 라벨 없음 |

> `status`의 실질은 지원불가 3건이 전부 맞은 것이다. 1건이 33%p인 클래스라
> 지표로서는 여전히 약하다. **평가셋 확장 전까지 이 수치를 성능 근거로 강하게 쓰지 마라.**
> `status`는 `flag`의 결정적 함수다(컴플라이언스 Rule 0, `config.py:338`). 별도 성능으로 세지 않는다.
> "순이득 +6~10%p"를 `flag`와 따로 근거로 쓰면 이중 계산이다 (P3-06).

> `is_receipt` 오탐 0/93 주석: 이전 `run_eval.py`의 오탐 검사는 `None.get`으로 도달 불가였다
> (P1-1 / P2-03 / P3-01). `2680010`에서 검사가 동작하게 고쳤고, **mock 입력으로만 발동을 확인했다**.
> 93행 재집계 결과(0건)는 그대로지만, 재실행 때 error 행이 파일에서 삭제되는 구조라
> 중간 거절이 있었는지는 복원할 수 없다. 첫 시도 거절률이 아니라 재시도 후 생존 결과다.

상세 경위는 프로젝트 문서 참조:
- `document/FINDINGS_2026-08-26_first_baseline.md` — 최초 측정, flag 0% 발견
- `document/FINDINGS_2026-08-28_variance.md` — 분산 34%p 발견부터 해소까지 (§9에 08-30 정정)
- `document/REVIEW_2026-10-12_P1.md` — 이 문서의 "바뀐 것/완료"를 코드와 대조
- `document/REVIEW_2026-10-12_P2.md` — 코드/평가 러너 결함 조사
- `document/REVIEW_2026-10-12_P3.md` — "macro 100%, citation 9/9는 가짜다" 가설 검증

---

## 지표 한계 (P3, 근거: `document/REVIEW_2026-10-12_P3.md`)

위 수치는 **학습셋 정확도**다. 일반화 성능으로 읽지 마라. 전부 [blocked] — 평가셋 확장이 선행돼야 한다.

- **macro 100%는 gatefix 이전부터 100%였다.** `receipt_run*`(gatefix 이전)부터 100%이고 10개 run의
  flag가 31건 전부 동일하다. 분류 단계는 RAG를 쓰지 않아 이후 수정의 영향을 받지 않는다.
  규칙(식당·카페·편의점 `확인필요`, 유류·주차 `지원불가`)은 같은 31장의 실패를 보고 작성됐다 (P3-04, P3-08).
  temperature 0 반복 일치는 독립 표본이 아니다.
- **citation 쿼리는 평가셋으로 튜닝됐다.** 후보 쿼리를 정답 청크(chunk 8) 순위로 골랐고,
  같은 지원불가 3건으로 9/9를 보고했다. 쿼리가 고정이라 `flag=지원불가`인 모든 입력이
  같은 컨텍스트를 받는다. 독립 표본은 3건이다 (P3-02, P3-03).
- **라벨이 vendor 업종 키워드 하나로 결정된다.** 주유소·주차장 → `지원불가`,
  식당·카페·편의점·숙박 → `확인필요`. 업종은 같은데 정답이 갈리는 대조 쌍 0건,
  `정상` 정답 0건 (P3-05).
- **negative set에 hard negative가 0건이다.** 37장이 라이브러리 샘플 사진이라
  메뉴판·견적서·결제내역 캡처 같은 경계 사례 검증이 없다 (P3-07).

---

## 이번에 바뀐 것

**`config.py`**
- `extract` 스키마에 `is_receipt: bool` 추가 + 판정 규칙 명시

**`pipeline.py`**
- `is_receipt=false`면 즉시 반환 (분류/컴플라이언스 스킵)
- `review_settlement`의 `classification=None` 케이스 집계 크래시 수정 (위 변경이 만든 회귀)
- override 게이트에 **noop 분기** 추가 — `classification.flag`가 override 이전에 이미
  `지원불가`였으면 게이트를 건너뛴다. 게이트의 목적은 *뒤집기 방어*인데
  안 뒤집는 재확인 케이스까지 걸려 `compliance_status`만 강등되고 있었다.
  건너뛴 경우 `override_noop`으로 기록 (`override_rejected`와 구분)

**`eval/`**
- `labels_nonreceipt.csv` 신규 — 37장 negative set (`.venv` 내 skimage/networkx/scipy/sympy 샘플)
- `run_eval_nonreceipt.py` 신규 — `run_eval.py`와 반대로 `.venv` 필터 없이 인덱싱
- `run_eval.py` — `is_receipt` 오탐(실영수증 거절) 검사 추가 (**추가 당시 도달 불가였음 — `2680010`에서 수정**)
- `eval/README.md` — 표/사용법 갱신

### 2026-10-12~13 REVIEW 대응 (`f05a14f`~`e63c93e`, 7커밋)

**`pipeline.py`**
- `process_pdf`: `convert_pdf_to_markdown`의 `finish_reason != "STOP"`이면 `.md` 쓰기와 delete→store 전에
  `RuntimeError`. 반환 dict에 `finish_reason` 포함. `raw_markdown` 재임베딩 경로는 `STOP`으로 간주 (`f05a14f`, P2-04)
- `_update_report`: 레코드를 파일 형식과 같은 4열로 통일. 두 번째 파일부터 나던 `IndexError`와
  청크 합계 오류 수정 (`31895bd`, P2-06). `manual/output/processing_report.md`는 08-21 값(문서 1, 431청크)이라
  다음 처리부터 갱신된다

**`app.py`**
- `/convert-by-chapters`: 분할 변환에 실패 구간이 있으면 `process_pdf` 호출 전에 502.
  실패 구간 목록은 `detail`에 포함 (`e63c93e`, P2-04 계열)

**`eval/`**
- `run_eval.py` / `variance_probe.py` / `survey_all.py`: `classification`·`compliance`가 `null`일 때의
  None 가드, `run_eval.py`의 `"error" in r is False`(항상 False) 수정. `is_receipt=false` 응답이
  error가 아니라 오탐 절로 집계된다 (`2680010`, P1-1 / P2-03 / P3-01)
- `run_eval.py`: `rec["raw"]`에 `override_noop` 수집. 리포트 출력은 없음 (`dc21321`, P1-2)
- `labels_prefilled.csv` 11행을 `국내여비(운임/숙박비/식비/일비)`로 교체 + `run_eval.py`의
  `LEGACY_SUB_ITEM`(옛 `want`를 담은 기존 jsonl용 명시 매핑 2개) (`18cfa3c`, P2-02)
- `labels_prefilled.csv`에 `gold_citation`·`gold_phrase` 추가(지원불가 3행), `score()`에 citation 절
  (P 핵심구절 포함 = 주, F 정답 문장 전체 포함 = 보조) 추가 (`c05388c`, P2-07 / P3-03)

> 부수 효과: `18cfa3c` 이후 gatefix_run2·3, queryfix_run2·3의 `sub_item` 수렴 검사 판정이
> `⚠ 베이스라인 이하`에서 `✅`로 바뀐다(65% → 68%, 순이득 +0%p → +3%p). 이전 문서에서 이 판정을 인용했다면 다시 볼 것.

---

## 배포 상태 (08-31 이후, `73ca4f6`~`eb123d5` 12커밋)

판정 로직(추출·분류·컴플라이언스) 변경 없음. `e934f4b` 이후 `eval/` 새 측정 결과 파일 없음 (출처: `STATE_DELTA_0831.md` §4).

- **스택**: `docker-compose.yml`은 `qdrant`(6333) + `fastapi`(5000)뿐. MongoDB 제거 (`daf2418`).
  배포 이미지는 `qdrant-client` local mode(파일 기반)로 `qdrant_data/`를 이미지에 COPY (`922ad8d`, `431bfd5`).
  **로컬(서버 모드)과 배포(파일 모드) 두 경로가 공존**하고, `config.py`의 `QDRANT_PATH` 환경변수가 가른다.
- **`Dockerfile.fastapi`**: multi-stage. COPY 대상은 `app.py config.py chunking.py embeddings.py pipeline.py`, `static`, `qdrant_data`.
  `e934f4b` 시점엔 `app.py` 한 줄뿐이라 compose 바인드마운트에 의존했다 (`431bfd5`에서 해소).
  이미지를 `docker build`만으로 검증하지 않으면 같은 패턴이 재발할 수 있다.
- **Render 배포**: 단일 컨테이너, `PORT` 환경변수 대응 (`c156b5d`). 이미지 크기·메모리는 README 서술이고 재측정하지 않았다.
- **문서 불일치 (확인함)**: README:131은 인덱스를 "466포인트, 20MB"로 적었으나
  `qdrant_data/collection/documents/storage.sqlite`는 5,894,144 bytes(≈5.6MB). `922ad8d` 커밋 메시지는
  "프롬프트 폴더 삭제"인데 `git show --stat`에 `prompt` 관련 변경이 없다.
- 이 외 `30acda8`(3-tier UI 목업), `a48b0a4`(검증 스크립트 `eval/`로 이동), README 관련 커밋은 상세 생략.

---

## 측정 돌리는 법

영수증 이미지는 **커밋하지 않는다.** 로컬 경로:
`C:\Users\jon49\Downloads\영수증\영수증` (105장)

앱이 떠 있어야 한다 (`docker ps` → `fastapi` 5000, `qdrant` 6333).

```powershell
# negative set 먼저 — 싸다 (extract에서 즉시 반환)
python eval\run_eval_nonreceipt.py --api http://localhost:5000 --images "<.venv 포함 경로>"

# 채점 (비싸다, 3회 ≈ 510원)
python eval\run_eval.py --api http://localhost:5000 --images "<영수증 폴더>"

# 분산 확인 (같은 이미지 3회, 단계별 동일성)
python eval\variance_probe.py --api http://localhost:5000 `
  --images "<영수증 폴더>" --labels eval\labels_prefilled.csv --ids r001 r002 r004

# /chat retrieval — 결정론이라 1회면 충분. Gemini 호출 없음 = 무료.
python eval\run_eval_chat.py --api http://localhost:5000
```

**순서: negative 3회가 전부 37/37일 때만 31장으로 넘어간다.** 비용의 대부분이 후자다.

**판정 기준: 3회 최솟값이 이전 3회 최댓값을 넘을 때만 개선으로 인정한다.**
1회 측정으로 채택/롤백을 결정하지 마라 — 그렇게 하다 네 번 연속 노이즈를 원인으로 착각했다.
비용은 31장 1회 ≈ 170원.

리포트에서 **`단일 클래스 수렴 검사`를 제일 먼저 본다.** 출력 종류가 1개면
정확도가 높아도 성능이 아니다.

---

## 완료

- **`is_receipt` 거절 경로** — negative 37장 recall 100% (3회), 기존 31장 오탐 0/93
- **`status`/`flag` 불일치** — 게이트 noop 분기. status 최솟값 97%,
  r001/r002/r004 3회 모두 `위반의심` (이전엔 3회 모두 `확인불가`)
- **`flag=지원불가` 검색 쿼리 고정** — 회의비 1개 → 금지조항 커버 2개.
  citation의 정답 조항 인용률 0/18 → 9/9 (3회). 교차오염 0건.
  `item`(LLM 출력) 쿼리는 측정 후 기각 — 단독으로 조항을 못 끌어온다
  (0.286 vs 고정 쿼리 0.427).
- **`/chat` retrieval 평가셋 + baseline** — `eval/labels_chat.csv` 24문항.
  `/search`는 결정론(3회 diff 0바이트)이라 1회 측정으로 충분.
- **guiideline.pdf h3 분할** — 세목 3개 병합 청크가 개별 조항을 못 찾게 하고 있었다.
  15 → 35청크. hit@1 55%→65%, colloquial 40%→60%, MRR 0.639→0.758.
  national_eval_rule.pdf(431청크)는 h3 편차가 커서 제외.

**2026-10-12~13 REVIEW 대응** (검증은 mock 또는 기존 jsonl 재채점만, 앱 실행·외부 API 호출 없음)
- **`process_pdf` finish_reason 가드** (`f05a14f`) — mock `("", "RECITATION")`, `("부분", "MAX_TOKENS")`에서
  예외 발생, 기존 `.md` 바이트 동일, `delete_chunks_for_file`/`store_chunks` 호출 0회. `("본문", "STOP")`은 기존 동작.
- **분할 변환 실패 구간 저장 방지** (`e63c93e`) — 1구간 실패 mock에서 502, detail에 실패 라벨 포함,
  `process_pdf` 호출 0회, 기존 `.md` 동일, 임시 PDF 삭제. 수정 전에는 `process_pdf`가 호출돼 `.md`가 바뀌는 것을 재현.
- **`_update_report` 4열 통일** (`31895bd`) — 리포트 사본에서 수정 전 `IndexError` 재현,
  수정 후 파일 2개 연속 처리 성공, 합계 476(431+35+10) = 각 행의 합. 원본 해시 불변.
- **`is_receipt` 오탐 검사 복구** (`2680010`) — mock `classification=null`에서 error 레코드 없음,
  `got.is_receipt==False`, 리포트에 오탐 절 출력. `queryfix_run1` 리포트는 변경 전후 바이트 동일.
  거절 행은 flag·status 분모에 들어가 오답으로 집계된다(판정 실패로 집계하기로 결정).
- **`override_noop` 수집** (`dc21321`) — mock `{"override_noop": true}`에서 `raw.override_noop == True`.
  `score()` 대상 jsonl 10개 리포트 바이트 동일.
- **sub_item 라벨 어휘 교체** (`18cfa3c`) — 10개 jsonl 재채점: 목록 외 `국내여비(식비)` 출력에 점수를
  주던 3곳(receipt_run2·3 r008, queryfix_run1 r009)이 오답이 되고, taxonomy 값을 낸 7개 run의 r003이 정답이 된다.
  새 CSV로 `want`를 만든 결과가 매핑을 적용한 옛 jsonl과 10/10 리포트 동일.
- **citation 채점** (`c05388c`) — queryfix_run1~3: P 9/9 / F 7/9. receipt·gatefix 6개 run(틀린 조항 인용)은 P·F 모두 0/3.
  `"유류비는 지원되지 않으며"` 단편은 P 정답 / F 오답. `score()`의 기존 절은 바이트 동일.

---

## 다음 할 일 (우선순위)

### 0. 미확인 열린 문제 — 최우선 확인: Gemini API 크레딧 소진

`STATE_DELTA_0831.md` §8 (2026-09-30 실행): 로컬 스택에서 `/chat` no_answer 4문항을 호출했더니 4건 모두
HTTP 500, Gemini 429 `Your prepayment credits are depleted`. 모든 LLM 호출이 같은 `GEMINI_API_KEY`를 쓰므로
`/classify-receipt` 등도 같은 오류일 가능성이 높고, Render 라이브 데모가 같은 키라면 서비스 불가일 수 있다.
**현재 상태는 확인하지 않았다.**
**이 문서의 모든 측정치는 크레딧 소진 전(08-31) 값**이라 지금도 재현된다는 보장이 없다. 재측정 전에 먼저 확인할 것.

### 1. README — 2주 일정상 이게 다음이다

세 기능 서사가 완성됐다.

### 2. 평가셋 확장 (영수증) — 병목

macro 100%는 천장이고, **다음 수정의 효과를 측정할 수단이 없다.**
게다가 `지원불가` 정답 3건이 정확히 주유2+주차1인데 금지 목록에 그 둘을 명시해서
leakage에 가깝다. 함께 넣은 렌터카·범용기자재(PC/노트북)·귀금속은 **검증 0건**이다.

보유 사진 142장을 전부 조사한 결과 실제 영수증은 105장뿐이고
(나머지 37장은 `.venv` 안의 scikit-image 샘플), 해당 유형 영수증은 없다.
**새 영수증 수집이 선행돼야 한다.**

필요한 것:
- 렌터카 / PC·노트북 / 귀금속 영수증 (금지 목록 검증용)
- 톨비 영수증 (주유비의 인정 대체 증빙 — 대조군)
- **개인카드 결제 영수증** — 현재 31장 전부 법인카드라 결제수단이 정답과 상관돼 있다
- `지원불가` 클래스를 3건 → 10건 이상으로 (지금은 1건이 33%p)
- 범용기자재(PC/노트북)·귀금속 영수증도 필요 — #2 쿼리 fix(`"국내여비 유류비 렌터카 주차비 청구 불가"`)는 guiideline.pdf chunk 8(국내여비 조항)만 겨냥해서 이 두 항목은 안 잡힌다. 해당 조항이 chunk 8에 없어 별도 쿼리가 필요한데, 이 유형 영수증이 평가셋에 0건이라 지금은 검증 자체가 불가능하다

### 3. `/chat` 답변 품질 미측정

retrieval만 쟀다(hit@1 65%). Gemini 답변 생성 단계는 라벨도 채점 방법도 없다.
LLM-judge 또는 사람 채점이 필요하다. 최소 검증: `no_answer` 4문항이 실제로
"찾을 수 없습니다"로 나오는지부터 확인.

### 4. score로 no_answer를 못 가른다

`no_answer` 4문항 top1 평균 0.4627 vs answerable 20문항 평균 0.5065 — 거의 안 갈린다.
`answer_confidence`를 max_score 기반으로 짠 로직이 이 데이터에선 안 먹는다.

### 5. chat 미포함 2건

`c05`(회의비 조항이 chunk13/17 양쪽에 중복 존재), `c10`(참고1 제출서류표, 표 검색 실패).
성격이 달라 따로 봐야 한다.

### 6. (c) `/review-settlement` — 미측정, UI 미노출

`document_match`(증빙서류 매칭) 배치 미연결, 라인별 `except RuntimeError`만 잡아서
그 외 예외엔 배치 전체가 500으로 죽는다(`app.py:410`). 프런트에도 탭이 없다.
Jina HTTP 실패는 `RuntimeError`라 **잡힌다** (이전 서술 정정, P2-10). 실제로 배치를 죽이는 경로는
(a) 분류·컴플라이언스의 `generate_content` 예외(429 quota 등), (b) `requests` timeout/ConnectionError,
(c) Qdrant `search` 예외다. 중간에 quota가 걸리면 앞서 성공한 라인까지 전부 버려진다. 예외 클래스는 코드상 추론이고 실행 확인은 없다.
2주 일정상 README에 "API만 존재, UI 미노출"로 명시하고 넘긴다.

### 7. `absolute_cap`이 구조적으로 죽어 있다

`flag=지원불가` → `sub_item="해당없음"` 고정(`config.py:298`)인데
`ABSOLUTE_CAP_RULES` 어디에도 `"해당없음"`이 없다 → `해당없음`이면 `unknown`.
게다가 반환값을 읽는 코드가 없다 (생성: `pipeline.py:493` / 소비: 없음. 러너도 `absolute_cap`을 수집만 하고 채점 0).
08-26 findings의 "r003 모텔 520,000원 캡 판정 미측정"은 캡 자체가 동작 안 한 것이었다.

**정정 (P2-08):** "항상 `unknown`"은 아니다. r003이 `sub_item=국내여비(운임/숙박비/식비/일비)`로 나온 7개 run에서
`absolute_cap=ok`다. 숙박비 캡이 아니라 "100만원 이상 심의 회부" 절차형 규칙(`config.py:203-208`)이 걸린 결과다.
즉 "캡이 동작 안 함"이 아니라 "엉뚱한 규칙으로 ok"였던 run이 있다. 같은 어휘 문제가 `ABSOLUTE_CAP_RULES` 키
(`국내여비(일비)`, `국내여비(식비)`, `config.py:218,231`)에도 있어서, 모델이 프롬프트를 지키면 이 키는 매칭되지 않는다.

수정하려면 taxonomy의 `sub_item` 출력을 바꿔야 해서 **분류 단계 회귀 위험**.
지금 평가셋은 천장이라 그 회귀를 잡을 수 없다.
→ **평가셋 확장(2번) 이후에.**

### 8. r003 `status` variance

숙박비 상한초과 케이스. `want=확인불가`인데 실행마다 `위반의심`으로 갈린다.
noop fix 이전 로그(`receipt_run2/run3.jsonl`)에서도 동일 — 이번 수정과 무관.
`classification.flag=확인필요`라 override 경로도 안 탄다.
08-28의 "분산 0%p"는 `flag` 한정이었다. `status`는 아직 흔들린다.
→ 원인 미확인. 08-28 findings §9-③에 기록. 평가셋 확장 후.

**새 근거 (P2-09, 10개 run의 r003):** `flag`는 10/10 고정이지만 `sub_item`이 갈린다.
`sub_item=해당없음` 3건은 검색 컨텍스트가 `(guide, nat×4)`로 고정되고 `status=확인불가` 3/3.
`sub_item=국내여비(운임/숙박비/식비/일비)` 7건은 컨텍스트가 달라지고 `위반의심` 5/7, `확인불가` 2/7.
`위반의심`은 `국내여비` 컨텍스트에서만 나왔다. 상관은 확정(n=10), 같은 컨텍스트에서도 2/7이 `확인불가`라 **인과는 미확정**.

### 9. override 채택 0건 (수정 B가 사실상 미작동)

게이트 차단이 0건이 됐는데도 채택도 0건이다.
현 평가셋에 "분류=확인필요인데 compliance가 뒤집어야 하는" 케이스가 없다.
→ 검증 불가. 평가셋 확장 후.

### 10. [fix-now, 미처리] h3 분할이 파일명 리터럴에 묶여 있다 (P1-3)

`pipeline.py:172` `split_at_level = 3 if filename == "guiideline.pdf" else None`.
같은 문서를 다른 파일명(예: 철자 교정 `guideline.pdf`)으로 재업로드하면 분할이 꺼지고 15청크 구성으로 돌아간다.
`labels_chat.csv`의 `gold_chunk_index`는 35청크 기준이라 chat 평가 전체가 에러 없이 틀린 값을 낸다.
코드 경로상 확정, 실제 재업로드는 확인하지 않았다 (확신 medium).

### 11. [fix-now, 미처리] 15청크용 chat 라벨이 레포에 없다 (P1-4)

커밋된 `labels_chat.csv`는 35청크 기준(`c01`=6)이고 baseline jsonl은 15청크 기준(`c01`=2)이다.
"개선 전" hit@1 55%를 레포만으로 재현할 방법이 없다. 15청크용 라벨 보존 여부만 정하면 된다.

### 12. [blocked, 평가셋 확장 후] 검색·평가 설계 결함 (REVIEW 번호 참조)

- **P2-01** `확인필요`+`해당없음`이면 컴플라이언스 검색 쿼리가 `"해당없음 한도 사용기준"`, `"해당없음 제출서류"`로 고정된다.
  10개 run 모두 26~28건이 같은 `sources`를 받아, `status`의 대부분은 영수증별 규정 검색 없이 나온 값이다.
  "검색 결과 없음" 폴백 분기는 도달 불가. `item`/`vendor`를 쿼리 재료로 쓰는 안은 "하지 말 것"에 해당.
- **P2-05** Qdrant payload에 `title`이 없는데 프롬프트와 API가 `title`을 읽는다. `sources[].title`은 항상 `""`.
  재임베딩으로 채우는 방식은 "national_eval_rule.pdf 재임베딩 금지"와 충돌.
- **P3-02** citation 쿼리가 평가셋 지원불가 3건으로 튜닝됐다. 유류·주차 외 지원불가 영수증이 있어야 일반화를 잴 수 있다.
- **P3-04** `확인필요` 쪽 규칙도 31장의 실패를 보고 작성됐다. 두 클래스 모두 held-out 없음.
- **P3-05** 라벨이 업종 키워드 하나로 결정된다. 대조 쌍·`정상` 정답 0건.
- **P3-07** negative set에 hard negative 0건.

---

## 하지 말 것 (이미 시도해서 실패)

- **분류 단계에 RAG 붙이기** — 불안정성을 고치는데 불안정 요인을 추가하는 것. 텍스트로 해결됐다.
- **추출 프롬프트 손대기** — `vendor`·`item`이 흔들려도 판정은 고정됐다. 금액·날짜만 위험해진다.
- **검색 쿼리에 `vendor` 넣기** — 고유명사("성수주유소")가 쿼리 벡터를 오염시킨다. 시도했다가 롤백.
- **한 번에 두 가지 수정** — C에서 그랬다가 뭐가 원인인지 못 가렸다.
- **상수값의 3회 일치를 재현성으로 읽기** — `absolute_cap`이 매번 `unknown`을 뱉는 것을
  "코드 판정이라 안 흔들린다"로 오독했다. 값이 실제로 계산되는지부터 확인해야 한다.
  temperature 0에서 같은 입력을 반복한 일치도 독립 표본이 아니다 — 10회 일치를 일반화 재현성으로 읽지 마라 (P3-08).
- **LLM 출력을 검색 쿼리 재료로 쓰기** — `item`을 넣어봤으나 단독으로는 조항을
  못 끌어왔다(휘발유 구입 → chunk8 미포함). 고정 쿼리가 더 높고 안 흔들린다.
- **상수 이름 보고 원인 짚기** — `MIN_CHUNK_SIZE=300`이 병합 원인인 줄 알고 100으로
  낮췄더니 완전한 no-op이었다. 패킹 조건이 OR라 `MAX_CHUNK_SIZE` 쪽이 실질 결정권을
  쥐고 있었다. 조건문을 읽어라.
- **national_eval_rule.pdf 재임베딩** — 431청크가 지금 citation 9/9를 내고 있다.
  h3 편차(11~22783자)가 커서 같은 분할 규칙도 못 쓴다.
- **검사 코드가 도달 가능한지 확인하지 않고 "0건"을 결과로 쓰기** — `is_receipt` 오탐 0/93은
  `None.get`으로 죽은 검사 옆에서 나온 값이었다. mock 입력 1건으로 검사가 실제로 발동하는지 먼저 확인한다 (P1-1 / P3-01).
- **튜닝에 쓴 샘플로 같은 지표를 보고하기** — citation 쿼리를 정답 청크 순위로 고르고 같은 3건으로 9/9를 냈다 (P3-02).
- **라벨·출력 어휘를 정본(taxonomy)과 대조하지 않고 정확도를 쓰기** — 라벨의 `국내여비(식비)`가 목록 외 값이라
  프롬프트를 지킨 출력은 오답, 어긴 출력은 정답이었다 (P2-02).

---

## 배경 맥락

- 목표: 포트폴리오 (AX 엔지니어 이직). **2주 내 지원 시작.**
- 예산: 주말 위주, 월 20시간
- Gemini API는 Tier 1 (유료 전환 완료). 31장 1회 ≈ 170원, RPD 150K
- 커밋 권한은 사용자에게 있다. **에이전트가 커밋하지 않는다.**
- 문서는 한국어, 코드·변수·로그·기술용어는 영어
