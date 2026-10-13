# 웹앱 구현 계획 (개정) — AI 연구비 집행 챗봇

> 개정일: 2026-06-29
> 원본 대비 변경: v1/v2 분리, 탈옥 로직 교체, 스택 단순화, 임팩트 측정 추가

---

## 0. 핵심 원칙 (먼저 읽을 것)

- **데모 먼저 동작 → 확장.** `/chat`은 이미 curl로 동작 확인됨. v1은 "그걸 보여주는 화면" 하나가 전부.
- **이 계획의 90%는 v2(확장)다.** 인증·admin·모니터링은 동작하는 데모가 포트폴리오에 올라간 *다음* 작업.
- **AX 평가축**: 인증/CRUD 같은 일반 웹 역량 X → **동작 + 임팩트 수치 + 도메인 특화** O.
- 시간 제약 월 ~20h. v1을 질질 끌지 말 것.

---

## 1. v1 — 지금 만들 것 (목표: 1~2 세션)

> 한 줄: 인증 없는 단일 페이지 챗 데모. 질문 → 답변 + 출처/신뢰도 표시.

### 범위
- **포함**: 질문 입력, 답변(markdown 렌더), 출처(source_file/title/score) 표시, 신뢰도 플래그, 로딩 상태
- **제외**: 로그인, 사용자 관리, admin, 시스템 헬스 대시보드, Next.js, nginx

### 스택 (단순화)
| 레이어 | 기술 | 비고 |
|---|---|---|
| 프론트 | **정적 HTML 1장 + vanilla JS + fetch** | FastAPI가 서빙 → CORS·컨테이너 추가 불필요 |
| markdown 렌더 | marked.js (CDN) | `answer`에 `**`, `*`, `\n` 포함됨 |
| 백엔드 | FastAPI (기존) | `GET /` 로 HTML 서빙 라우트만 추가 |

### `/chat` 실제 스펙 (확인됨)
- `POST /chat`, `multipart/form-data`, field `query`
- 응답: `{ query, answer(markdown), sources: [{score, source_file, title, chunk_index}] }`

### 신뢰도 플래그 (탈옥 로직 대체 — 중요)
원본의 `has_sources:false → jailbreak_suspected:true` 는 **폐기.**
→ 정상적으로 답 못 찾는 케이스도 전부 false positive로 잡힘. jailbreak와 무관.

대신 **`answer_confidence`** 도입 (max source score 기준):
- `max_score >= 0.55` → 정상
- `0.45 ~ 0.55` → ⚠️ "근거가 약합니다. 담당자 확인 권장"
- `< 0.45` 또는 sources 없음 → "이 문서 범위 밖 질문일 수 있습니다"

> 컴플라이언스 도메인 가치: 틀린 규정을 자신있게 안내 = 사고. confidence gating이 핵심 차별점.

---

## 2. 임팩트 측정 (신규 — README용)

> AX 포트폴리오의 핵심. v1 데모 직후 바로 측정.

- **정확도**: 대표 질문 5~10개 선정 → 답변을 맞음/부분/틀림 수기 평가. 정답률 % 기록.
- **속도 비교**: "규정집(516p)에서 수작업으로 해당 조항 찾기 N분" vs "챗봇 X초".
- **출처 검증**: 답변이 인용한 chunk가 실제 정답 조항인지 확인 (RAG 환각 여부).
- 이 수치를 README 상단에 배치.

---

## 3. v2 — 확장 (데모 + 임팩트 확보 *후*)

> 원본 계획 대부분이 여기로 이동. 순서를 미룬 것이지 버린 게 아님.

### 우선순위
1. **쿼리 로그** (`query_logs`) — v1에서도 익명으로 가볍게 넣어도 됨(본인 답변품질 디버깅용). user_id 결합은 인증 후.
2. **인증** — JWT **access token만** (refresh는 데모 가치 낮음, 후순위). `passlib` bcrypt.
3. **admin 화면** — 사용자 목록, 쿼리 로그 열람. 이때 React 단일 페이지(Vite) 검토.
4. **시스템 헬스** — 마지막. 데모 가치 대비 비용 높음.

### MongoDB 컬렉션 (원본 유지, 일부 수정)

`users` (원본 그대로 OK)
```json
{ "_id":"ObjectId", "username":"홍길동", "user_id":"gildong01",
  "hashed_password":"bcrypt", "role":"user|admin",
  "created_at":"ISODate", "is_active":true }
```

`query_logs` (jailbreak → confidence 로 수정)
```json
{ "_id":"ObjectId", "user_id":"gildong01 | anonymous",
  "query":"...", "answer":"...",
  "sources":[{"source_file":"...","score":0.6}],
  "max_score":0.6, "answer_confidence":"normal|weak|out_of_scope",
  "timestamp":"ISODate" }
```

### 엔드포인트 (원본 유지, v2로 분류)
- 인증: `POST /auth/login`, `GET /auth/me` (refresh 후순위)
- admin: `GET /admin/users`, `POST /admin/users`, `PATCH/DELETE /admin/users/{id}`, `GET /admin/logs`, `GET /admin/health`
- 사용자: `POST /chat`(JWT 추가), `GET /chat/history`

### 스택 — v2 단계에서만
- React 단일 페이지(Vite build) → FastAPI가 정적 서빙. **Next.js App Router route group은 이 규모에 과함.**
- nginx 리버스 프록시: docker 내부 통신엔 불필요. 외부 배포 시점에만 검토.

---

## 4. 미결 사항 — 결정함

| 항목 | 결정 |
|---|---|
| 비밀번호 분실 처리 | **데모 생략** (관리자가 재설정) |
| 자가 회원가입 | **불허** — 관리자만 생성, 데모는 사용자 2~3명 시드 |
| 탈옥 자동 차단 | **하지 않음** — confidence 플래그 + 로그만. 자동 차단은 false positive 위험 |
| Next.js 컨테이너화 | **v1에서 삭제.** v2에서 React 단일 페이지로 대체 검토 |
| API 도메인 분리 / nginx | **불필요** — FastAPI 단일 출처 서빙 |

---

## 5. 안티패턴 경계 (재확인)

- 이 문서를 "잘 정리된 계획"이라는 만족감으로 끝내고 실행을 미루지 말 것.
- **다음 액션은 v1 단 하나**: FastAPI `GET /` HTML 서빙 + 챗 페이지. 그 외 전부 v2.
- v2 항목을 v1에 끌어오고 싶은 충동 = scope creep. 데모 + 임팩트 측정 끝나기 전엔 손대지 않음.
