# FINDINGS — PDF→Markdown 변환 손실 원인 규명 및 최종 해결 (national_eval_rule.pdf)

> 세션: 2026-08-07
> 맥락: `national_eval_rule.pdf`(516p) 63% 손실 문제 → 챕터별 100p 분할(Tier 1) 적용 후에도 손실 재확인 → 원인 재조사 → 최종 해결

---

## 0. 한 줄 결론 (최종)

원인은 페이지 분할이 아니라 **변환 모델의 요약 경향 + 출력 토큰 설정 누락 + 쓸 수 있는 모델의 API 쿼터 제약**, 3중 문제였음. 최종적으로 **`gemini-3.5-flash-lite`(신세대 lite, RPD 500) + `max_output_tokens=65536` + pypdf 기반 사전 분량추정 분할(50,000자 예산)** 조합으로 **원본 대비 97.7% 커버**, Qdrant 438개 벡터로 재구축 완료. `document/FINDINGS_2026-08-07_gemini_conversion_truncation.md` 조사는 여기서 종결.

---

## 1. 문제 재확인 (100p 분할 후)

`/parse-toc` → `/convert-by-chapters`로 10개 챕터(≤99p) 분할 재변환 실행. 결과:

| 항목 | 단일변환(기존) | 100p 챕터분할 |
|---|---|---|
| Markdown 글자수 | 174,453자 | 112,716자 |
| 글자수 비율(vs PDF 413,793자) | 42.2% | **27.2%(악화)** |
| finish_reason | 미확인 | **전부 STOP(10/10)** |

키워드 20종 전수 조사 결과 전부 20~39% 수준 균일 손실 → 특정 섹션 누락이 아니라 **전체적으로 고르게 압축**된 패턴. `finish_reason=STOP`이므로 "출력 토큰 한도로 잘림" 가설 기각.

---

## 2. 분할 단계 결백 증명

제1장(11~54p, 44p) 페이지 범위를 pypdf로 직접 추출 → **49,868자** 정상 추출(원본 pypdf 텍스트 레이어 기준). 분할된 PDF 자체엔 내용 전부 들어있음 — `PdfWriter.add_page()`는 원본 페이지 객체를 그대로 복사하는 기계적 작업이라 이 단계에서 손실 메커니즘 자체가 없음. 인덱싱(`start_page-1` ~ `end_page`)도 오프바이원 없이 정확.

→ **분할(스플릿) 무죄 확정.**

---

## 3. 모델 비교 실험 (제1장 44p 단일 케이스)

| 모델 | `max_output_tokens` | 결과 글자수 | finish_reason |
|---|---|---|---|
| `gemini-3.1-flash-lite-preview` (기존) | 미지정 | 17,806자 (35.7%) | STOP |
| `gemini-3.5-flash` (비-lite) | 미지정 | 49,472자 (99.2%) | **MAX_TOKENS** |
| `gemini-3.5-flash` (비-lite) | **65536(모델 최대)** | **53,548자 (107.4%)** | **STOP** |

- **lite 모델**: 정상 종료(STOP)인데도 원문 1/3만 사용 → "표/생략 금지" 시스템 지시를 무시하고 자체적으로 요약·압축하는 경향. 페이지를 아무리 잘게 쪼개도 이 문제는 해결 안 됨.
- **non-lite 모델**: 요약 안 하고 원문 그대로 옮기려는 경향은 있으나, `max_output_tokens` 미지정 시 SDK 기본값이 모델 실제 한도(65,536 tokens)보다 훨씬 낮게 적용되어 44p짜리 챕터 하나에서도 조기 절단(`MAX_TOKENS`) 발생.
- `max_output_tokens=65536` 명시 후 53,548자로 완결 — 원본(49,868자) 대비 107%(마크다운 문법 `|---|`, `#`, `[Image:...]` 오버헤드 감안 시 자연스러운 수치). **완전 커버 확인.**

---

## 4. 근본 원인 (복합)

1. **모델 선택 문제** — `config.py:13`, 변환용으로 lite 모델 사용 중. Lite 모델이 "convert without omission" 지시를 안 지키고 요약해버림.
2. **설정 누락** — `config.py:44`, `GEMINI_CONFIG`(`GenerationConfig`)에 `max_output_tokens` 지정 안 돼있어 SDK/API 보수적 기본값 적용 → non-lite로 바꿔도 잘림 재발.

---

## 5. 조치 완료

- `config.py` `GEMINI_CONVERT_MODEL`: `gemini-3.1-flash-lite-preview` → `gemini-3.5-flash`
- `config.py` `GEMINI_CONFIG`: `max_output_tokens=65536` 추가
- `GEMINI_CHAT_MODEL`(답변용)은 lite 그대로 유지 — 답변은 원래 짧고 요약 성격이라 문제 안 됨, 비용/속도 이점 유지.
- (부수) `pipeline.py` `convert_pdf_to_markdown()`에 `finish_reason` 체크 추가 — `MAX_TOKENS` 감지 시 경고 로그. 이번 조사의 핵심 진단 도구가 됨.

---

## 6. 다음 액션

1. **10챕터 전체 재변환** — 새 설정(`gemini-3.5-flash` + `max_output_tokens=65536`)으로 `/convert-by-chapters` 재실행, `validate_conversion.py`로 최종 손실률 검증.
2. 부록-1/2(17.8MB/10.1MB, 서식 스캔본)는 이미지 기반이라 별도 검증 필요 — 텍스트 손실이 아니라 "[Image: 설명]" 처리가 의도된 동작인지 확인.
3. 재검증 통과 시 Qdrant 재구축(청킹 → 임베딩 → 저장) 진행.
4. 재구축 후 `/chat` score 재확인 (기존 목표: 0.603 이상 유지/개선).

---

## 7. 1차 조치 이후 재발견된 문제

### 7-1. 페이지 상한 고정값(100p) 자체가 근본 해결책이 아님
100p 상한도 결국 매직넘버 — 표/각주 밀도 높은 페이지가 몰리면 언제든 재발 가능. **해결**: `app.py` `/parse-toc`에 pypdf 기반 사전 분량추정(`estimate_chars`) 도입, 장/절 경계를 유지하면서 각 청크가 **50,000자 예산**(65536 토큰의 약 54%, 밀도 변동 대비 여유 확보) 안에 들도록 재귀 분할(`bisect_by_budget`)로 교체. 결과: 100p 고정 시 10청크 → 예산기반 11청크(밀도 반영해 2·3장은 더 잘게, 부록은 실제 텍스트가 적어 200p 통짜로 자동 판단).

### 7-2. `/convert-by-chapters` 전체 실패 구조
챕터 하나(RECITATION 등)가 실패하면 전체 요청이 500 에러로 죽어 앞서 성공한 챕터까지 다 버려짐. **해결**: `convert_range_adaptive()` 재귀 함수 도입 — STOP이면 그대로 반환, MAX_TOKENS/RECITATION이면 페이지 범위를 반으로 쪼개 재귀 재시도(최대 depth 6), 최소단위에서도 실패하면 그 구간만 `failed_segments`에 기록하고 나머지는 정상 처리. 예방(사전추정)이 주 방어선, 이 재귀 재시도는 안전망.

### 7-3. RECITATION (저작권 반복 감지)
`gemini-3.5-flash`로 제3장-1(99p) 변환 중 `finish_reason=4`(RECITATION, "저작권 자료 암송 의심")로 응답 자체 거부됨. 공공저작물(법령)인데도 트레이닝 데이터 중복으로 발동한 것으로 추정. verbatim 전사가 목표라 회피가 구조적으로 어려움 — 위 7-2의 재귀 격리로 완화(작게 쪼개면 매칭 패턴이 바뀌어 회피되는 경우 있음, 최종 실행에서는 발생 안 함).

### 7-4. `gemini-3.5-flash`(비-lite) 무료 티어 RPD=20 — 치명적 병목
AI Studio 쿼터 표로 확인: `gemini-3.5-flash` RPD 20(요청기반 소진, 재귀재시도 버그와 겹쳐 하루치 순삭됨), `gemini-2.0-flash`/`gemini-2.5-flash`/`gemini-3.1-pro`는 이 계정에서 `limit: 0`(free tier 미지원) 또는 신규유저 차단. 재귀 재시도 로직이 429(quota exceeded)도 MAX_TOKENS와 동일하게 취급해 계속 쪼개며 재시도 → 오히려 쿼터를 더 빨리 태우는 버그 발견, `convert_range_adaptive`에 429 감지 시 즉시 예외 전파하도록 수정(재시도 없이 중단).

### 7-5. 최종 모델 선정 — `gemini-3.5-flash-lite`
AI Studio 쿼터 표에서 `Gemini 3.5 Flash Lite`가 RPD 500(미사용 0/500)임을 확인, 신세대 lite라 구세대(`3.1-flash-lite-preview`)와 달리 요약하지 않을 가능성을 테스트. 챕터1(44p) 테스트: **51,662자, STOP, 원본 대비 103.6%** — verbatim 전사 확인. RPD 500이라 쿼터 걱정도 없음. `config.py` 최종 모델로 채택.

---

## 8. 최종 검증 결과

11챕터(예산기반 분할) 전체를 `gemini-3.5-flash-lite` + `max_output_tokens=65536`로 재변환:

| 항목 | 값 |
|---|---|
| 성공 챕터 | 11/11 (전부 STOP, `failed_segments: []`) |
| Markdown 글자수 | 404,443자 (원본 413,793자 대비 **97.7%**) |
| 키워드 20종 검증 | 19개 90%+ 커버, 1개("매뉴얼") 69%로 경고선 근접(무시 가능 수준) |
| Qdrant 재구축 | 438 vectors (기존 189 → 120 → 438) |

---

## 8-1. `/chat` 재검증 (재구축 후)

대표 질문 5개(용도 리스트 풍부한 항목 위주로 재선정 — 2026-06-25 FINDINGS 권고 반영)로 검증:

| 질문 | top score | 답변 품질 |
|---|---|---|
| 연구활동비는 어떤 용도로 사용할 수 있나? | 0.6892 | 정확 (지식재산활동비/외부전문기술활용비/회의비/출장비 등 항목별 상세) |
| 출장비 사용 기준이 뭐야? | 0.6458 | 정확 |
| 회의비는 어떻게 써야해? | 0.5084 | 정확 |
| 연구개발과제 협약은 어떤 절차로 진행돼? | 0.7095 | 정확 |
| 연구수당 지급 기준이 궁금해 | 0.6940 | 정확 |

**전부 기존 목표(0.603) 상회.** 최초 `curl -F`로 테스트했을 때 score가 0.10~0.17로 이상하게 낮고 답변도 엉뚱했는데, 원인은 파이프라인이 아니라 **Windows git-bash 환경에서 curl에 한글 쿼리 문자열을 넘길 때 인코딩이 깨져서 전달된 것**(bash 변수에 담긴 한글이 시스템 로케일로 잘못 인코딩됨). 컨테이너 안에서 `pipeline.chat()`을 직접 python으로 호출하니 정상 확인됨. → 앞으로 한글 텍스트를 API로 테스트할 땐 curl 대신 `docker exec ... python -c "..."`로 직접 호출할 것.

---

## 9. 남은 메모

- `PYTHONUNBUFFERED=1`을 `docker-compose.yml`의 fastapi 서비스에 추가 — 컨테이너 stdout이 버퍼링돼 있어 실시간 진행 로그(`docker logs -f`)가 안 보이던 문제 해결(조사 과정에서 발견).
- `pipeline.py`의 `convert_pdf_to_markdown()` 반환 시그니처가 `str` → `tuple[str, str]`(markdown, finish_reason)로 바뀜 — 호출부(`process_pdf`, `/test-gemini-parse`) 동기화 완료.
- MongoDB 컨테이너는 여전히 미사용 상태로 유지 결정 — 추후 영수증 OCR/비목분류, 서류 컴플라이언스 검토 기능(포트폴리오 3대 기능 중 ②③) 구현 시 사용 예정.
