# PROJECT_STATUS.md

> AI 사업비 집행 챗봇 — 세션 간 연속성 문서
> 최종 갱신: 2026-08-19

---

## 2026-08-19 세션 갱신 (최신 상태)

> 아래 "1~4절"은 2026-06-27 기준 기획 스냅샷이라 현재와 상당 부분 다름(당시엔 킬러 데모 미착수 상태). 최신 진행상황은 이 절과 `DEV_LOG.md`를 참고할 것.

### 현재 상태 요약
3대 기능(① 규정 Q&A ② 영수증 분류 ③ 서류 컴플라이언스) 전부 동작 중 — 6/27 계획 대비 진행 완료.

- **① `/chat`** — RAG 기반 규정 Q&A. 문서 법적 등급(법률 > 시행령 > ... > 사업지침) 자동분류가 검색 컨텍스트에 반영됨.
- **② `/classify-receipt`** — 영수증 vision 추출 → 고정목록 비목분류 → 컴플라이언스 검토(3단계) → **증빙서류 자동매칭**(`document_match`, 4단계, 이번 세션 신규).
- **③ `/review-settlement`** — 정산보고서 일괄 검토(영수증 N건에 `classify_receipt()` 재사용 + 비목별 계상비율 캡 검증).

### 이번 세션(2026-08-19) 작업 — 증빙서류 자동매칭
- `/classify-receipt`에 `supporting_docs`(선택, 다중 이미지/PDF) 파라미터 추가. LLM 1회 호출로 필요서류 목록 대 첨부파일을 대조해 `matched`/`missing`/`unclear` 3단계로 판정.
- 8/16에 스코프 제외했던 "실제 서류 첨부 여부 판정"을 이번 세션에 다시 포함시키기로 결정 변경.
- 웹 UI(`static/index.html`)에도 반영, Playwright로 실제 브라우저 렌더링 확인 완료.
- 배치(`/review-settlement`)엔 아직 미연결 — 다음 세션 후보.
- 기술 스펙: `docs/document_match.md`. 설계결정/검증결과 상세: `DEV_LOG.md` 2026-08-19(4) 항목.

### 남은 것
- 배치(`/review-settlement`)에 증빙서류 그룹핑 연결
- 실제 증빙서류 샘플([별지N] 등) 확보 후 매칭 정확도 검증(현재 미실행 상태)
- README "임팩트 측정" 섹션 채우기(수치는 이미 확보됨 — `tests/impact_20260810_021235.json`, `tests/speed_benchmark.md`)
- 기록만 하고 미해결로 남긴 이슈 3건(수정 안 함): doc_tier가 컴플라이언스 검색 랭킹에 미반영, `review_settlement` 예외처리 범위 부족, 매칭 단계 "한 파일=한 항목" 규칙 모델 미준수 — 상세는 `DEV_LOG.md` 참고.

---

## 0. 한 줄 요약

국가연구비(창업탐색비) 집행 컴플라이언스 챗봇. **AX 엔지니어 포트폴리오용**.
3대 기능: ① 규정 PDF 기반 Q&A, ② 영수증 OCR/비목 분류, ③ 서류 컴플라이언스 검토(항목이 올바른 위치에 채워졌는지).

---

## 1. 포트폴리오 전략 (세션 재정립)

### 타겟: AX (AI Transformation) 엔지니어
- ML 리서처 아님. 기존 LLM/RAG/agent로 **실제 업무 프로세스 자동화 + 임팩트**가 평가축.
- 핵심은: **실제 동작(end-to-end) + 임팩트 수치 + 도메인 특수성.**

### 시간 제약: 주말만, 월 ~20h (실작업 세션 월 4회)
- "상용화"는 불가능. scope를 잔인하게 컷한다.

### 방향 전환: bottom-up → top-down
- 챗봇 먼저 동작 → 역으로 필요한 만큼만 전처리 튜닝

### 버릴 것 (확정)
- GPU 임베딩 서버(Jina v3) → **cloud embedding API**로 교체 (완료)
- Marker, 멀티 PDF 완벽 처리, 인증/권한/모니터링
- app.py 모듈화, 청킹 "5개냐 685개냐" 무한 튜닝

### 남길 것 (집중)
- 살아있는 1개 PDF로 **`/chat` end-to-end 동작** (완료)
- **킬러 데모 1개**: 표 구조 보존 → 서류 항목이 올바른 위치에 채워졌는지 검증 (도메인 해자)
- 데모 UI 또는 2분 데모 영상
- README: 문제정의 + 의사결정 진화 서사 + **임팩트 추정**(수작업 N분 → 자동 X초)

---

## 2. 인프라 / 자산 현황 (2026-06-27 기준)

| 자산 | 위치 | 상태 |
|---|---|---|
| git monorepo (app.py 등) | 노트북 `~/Documents/ai_sumr_pj` | **생존**, GitHub private push 완료 |
| embedding_server (Jina v3) | cloud (Jina Cloud API) | **전환 완료** |
| Qdrant 167 chunks (national_eval_rule) | 노트북 Docker | **동작 중** (`national_eval_rule.pdf` 167 chunks 임베딩 완료, score 0.6039, `/chat` 정상 작동) |
| GPU (RTX 4070) | 워크스테이션 | 소실 → Jina Cloud 임베딩 API 전환 완료 |

### 기술 스택 (현재)
- API: FastAPI (port 5000), Docker, WSL2/Windows
- Storage: Qdrant(vector), MongoDB
- LLM/Parsing: Gemini `gemini-3.1-flash-lite-preview` (File API, RPD 500)
- Embedding: **Jina embeddings v3 (Jina Cloud API, 1024-dim, task별 맞춤 임베딩)**

### git 히스토리 (최근 커밋)
```
da423fc feat: Gemini 3.1 전환, uuid point ID, clean_markdown 개행 처리
47ad312 fix: parse-toc offset 자동 계산 추가
2e4c57c feat: parse-toc 그리디 분할, convert-by-chapters 구현
9981a85 feat: File API 전환, 배치 처리, 리포트 생성 추가
af526f3 init: Gemini 기반 PDF 처리 파이프라인
```

---

## 3. 진행 상황 및 완료 여부 (기존 우선순위 대비)

### 기존 우선순위 항목

| 번호 | 항목 | 상태 | 비고 |
|---|---|---|---|
| 1 | `/chat` 최소 구현 | ✅ 완료 | RAG 기반 Q&A 완성 (Jina Cloud query 임베딩 + Qdrant 검색 + Gemini 3.1 답변) |
| 2 | 답변 오류 원인 분리 | 🔄 일부 | 검색 약점 = 청킹 문제로 분리 및 분석 진행 중 |
| 3 | `clean_markdown` regex 검증 | ⏭️ 건너뜀 | 3-Tier 청킹 파이프라인 설계로 인해 상대적으로 중요도 낮아져 생략 |
| 4 | GPU → cloud embedding | ✅ 완료 | GPU 서버 철수 및 Jina Cloud 임베딩 API로 완전 교체 |
| 5 | 킬러 데모 | ❌ 미착수 | 서류 항목 위치 검증 기능 (추후 진행 예정) |
| 6 | README | ❌ 미착수 | 포트폴리오 서사 작성 (추후 진행 예정) |

### 이번 세션 추가 구현 사항 (기존 계획 외)
- **3-Tier 청킹 파이프라인 설계 및 Tier 1 탐지 구현**:
  - `detect_chunking_tier`, `detect_toc`, `extract_first_pages_text` 구현
- **Tier 2 Heading 청킹 구현**:
  - `chunk_by_markdown_heading` 구현 (breadcrumb prefix 포함하여 맥락 보존)
  - `detect_heading_structure` 기반으로 process_pdf 내에서 Tier 2와 Tier 3 자동 분기 처리
- **Qdrant delete 버그 수정**:
  - 기존 raw dict 매칭 삭제 방식의 오류 해결 -> typed `FilterSelector`, `Filter`, `FieldCondition`을 통한 정확한 삭제 처리
- **디버그용 `/detect-tier` 엔드포인트**:
  - 업로드된 PDF의 chunking tier를 미리 탐지하고 TOC 매칭 라인 등을 시각적으로 확인하는 테스트 엔드포인트 추가

---

## 4. 추후 진행 (남은 큰 작업)

1. **Tier 1 파이프라인 통합**
   - `process_pdf` 진입 전에 Tier를 자동 감지해서 라우팅하는 기능 구현.
   - 현재는 `/detect-tier`가 탐지만 수행하며, 실제 Tier 1 처리 (`/parse-toc` -> `/convert-by-chapters`)는 수동 단계로 분리되어 있음.
2. **킬러 데모 구현**
   - 서류 항목 위치 검증 기능 개발 (표 구조 보존 검증 등).
3. **질문 5개 품질 체크**
   - 현재 '학생인건비' 1개 케이스만 테스트 완료된 상태. 나머지 4개 질문 케이스 테스트 및 품질 검증 필요.
4. **ehwa/guiideline 재임베딩 및 테스트**
   - 새로운 청킹 알고리즘을 적용하여 Tier 2 경로 전체 프로세스(임베딩, 검색, 챗) 검증.

