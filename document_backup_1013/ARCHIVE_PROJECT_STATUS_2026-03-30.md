# AI 사업비 집행 컴플라이언스 챗봇 - 개발 현황

**최종 업데이트:** 2026-03-30  
**프로젝트 목표:** 정부 연구비 집행 규정 준수를 위한 AI 어시스턴트

---

## 📋 프로젝트 개요

### 핵심 기능 (3가지)
1. **질의응답 (Q&A)**: 공식 매뉴얼 기반 정확한 답변 제공
2. **영수증 검증**: OCR → 비목 분류 → 필수 서류 체크
3. **서류 컴플라이언스**: 사유서/공문 내용 자동 검증

### 기술 스택
- **백엔드**: FastAPI (Python)
- **벡터 DB**: Qdrant (로컬 Docker)
- **문서 DB**: MongoDB (로컬 Docker)
- **PDF 변환**: Gemini 2.5 Flash-Lite (직접 파싱)
- **임베딩**: Jina v3 (워크스테이션 GPU, 1024차원)
- **LLM**: Gemini 2.5 Flash-Lite (무료)
- **인프라**: Docker Compose + Tailscale VPN

---

## 🏗️ 시스템 아키텍처

```
노트북 (Docker, 포트 5000)
  ├── FastAPI (app.py) - 메인 서버
  ├── MongoDB (27017) - 카테고리, 영수증
  └── Qdrant (6333) - 벡터 저장소
        ↓ Tailscale VPN (100.88.194.30)
워크스테이션 (Docker Compose)
  └── embedding-server (5001) - Jina v3 GPU
        ↓ API 호출
Gemini API (Google Cloud)
  ├── PDF 직접 파싱 (gemini-2.5-flash-lite)
  ├── 챗봇 응답 (gemini-2.5-flash-lite)
  ├── 메타데이터 추출
  ├── OCR 처리
  └── 노이즈 패턴 감지
```

---

## ✅ 완료된 작업

### Phase 1: 인프라 구축 (2026-03-05 ~ 03-10)
- [x] 워크스테이션 GPU 서버 구축 (Jina v3 임베딩)
- [x] Tailscale VPN 설정 (노트북 ↔ 워크스테이션)
- [x] Qdrant 벡터 DB 설정
- [x] MongoDB 설정

### Phase 2: PDF 처리 파이프라인 (2026-03-10 ~ 03-13)
- [x] Marker PDF 변환 서버 구축 (CPU 모드)
- [x] MarkItDown → Marker 전환 (표 구조 보존 우선)
- [x] Docker Compose로 워크스테이션 서버 통합
- [x] VRAM 부족 문제 해결 (CPU 강제 모드)

### Phase 3: 노트북 환경 통합 (2026-03-17)
- [x] n8n 제거 (FastAPI로 완전 전환)
- [x] MarkItDown 코드 제거 (Marker로 단일화)
- [x] Docker Compose 재구성 (FastAPI + MongoDB + Qdrant)
- [x] .env 환경변수 관리 (GEMINI_API_KEY)
- [x] 노이즈 제거 패턴 추가 (이미지 참조, HTML 태그, 괄호)

### Phase 4: 통합 테스트 (2026-03-17)
- [x] 전체 파이프라인 실행 (ehwa_uni.pdf, 2.1MB)
  - 변환 시간: 14분 56초
  - 생성 청크: 14개
  - 저장 벡터: 14개
- [x] 검색 기능 테스트 성공 (71% 유사도)
- [x] `/search` 엔드포인트 GET 방식 전환

### Phase 5: PDF 파서 비교 및 Gemini 전환 (2026-03-18 ~ 03-19)
- [x] MarkItDown vs Marker raw 비교 테스트 (ehwa_uni.pdf 기준)
- [x] Gemini 직접 파싱 테스트 엔드포인트 (`/test-gemini-parse`)
- [x] Marker 서버 비활성화 (워크스테이션 docker-compose.yml에서 제거)
- [x] app.py Gemini 전환 완료 (Marker → Gemini 2.5 Flash-Lite)
- [x] ehwa_uni.pdf 재처리 성공
  - 변환 시간: 24초
  - 생성 청크: 685개 (Marker 14개 대비 대폭 증가)
  - 검색 유사도: 66% (한글 깨짐 없는 깨끗한 데이터)
- [x] FastAPI `--reload` 핫 리로딩 설정 (docker-compose.yml)

---

## 📊 현재 데이터 상태

### Qdrant 컬렉션
- **컬렉션명**: `documents`
- **총 벡터 수**: 1,420개 (3개 문서, Gemini 파싱)
- **벡터 차원**: 1024 (Jina v3)
- **거리 측정**: Cosine Similarity

| 파일명 | 크기 | 청크 수 | 상태 |
|--------|------|---------|------|
| ehwa_uni.pdf | 2.1MB | 685 | ✅ 정상 |
| guiideline.pdf | 0.7MB | 652 | ✅ 정상 |
| national_eval_rule.pdf | 34MB | 83 | ⚠️ 불완전 (출력 토큰 한도로 잘림) |

---

## 🔧 주요 파일 구조

### 노트북 프로젝트 (`/mnt/c/Users/jon49/Documents/ai_sumr_pj/`)
```
├── .env                    # GEMINI_API_KEY (Git 제외)
├── .env.example            # 환경변수 템플릿
├── .gitignore
├── .git/                   # Git 버전관리 (2026-03-19 초기화)
├── docker-compose.yml      # MongoDB + Qdrant + FastAPI
├── Dockerfile.fastapi      # FastAPI 컨테이너
├── app.py                  # 메인 서버 (Gemini File API 기반)
├── requirements.txt        # Python 패키지
├── manual/                 # PDF 문서 + 변환 결과물
│   ├── ehwa_uni.pdf
│   ├── guiideline.pdf
│   ├── national_eval_rule.pdf
│   └── output/             # Gemini 변환 결과 markdown + 처리 리포트
├── mongodb_data/           # MongoDB 데이터
└── backup/                 # 이전 버전 백업
```

### 워크스테이션 (`C:\Users\jon49\embedding_server\`)
```
├── docker-compose.yml      # embedding-server만 운영 (marker-server 제거)
├── embedding/
│   ├── Dockerfile
│   ├── embedding_server.py
│   └── embedding_requirements.txt
└── marker/                 # 백업 보관 (비활성화)
```

---

## 🔄 전체 파이프라인 플로우

### 문서 변환 및 저장 (`/convert-embed-store`)
```
1. PDF 업로드 (FastAPI)
   ↓
2. Marker 변환 (워크스테이션 CPU, ~15분/2MB)
   ↓
3. 노이즈 제거 (노트북)
   - 이미지 참조 제거: ![](_page_X_Picture_Y.jpeg)
   - HTML 태그 제거: <mark>, <u>
   - 괄호 정리: ('、)」
   - 페이지 번호 제거
   ↓
4. 목차 제거 (노트북)
   ↓
5. 청킹 (노트북, 1500자, 구조 기반)
   - 제N장/제N절
   - ①②③ (원 숫자)
   - ⅠⅡⅢ (로마 숫자)
   ↓
6. 필터링 (노트북)
   - 50자 미만 제거
   - 세로 표 제거
   - 괄호/기호 비율 검증
   ↓
7. GPU 임베딩 (워크스테이션 Jina v3)
   ↓
8. Qdrant 저장 (노트북)
```

### 검색 (`/search`)
```
1. 쿼리 입력
   ↓
2. GPU 임베딩 (워크스테이션)
   ↓
3. Qdrant 벡터 검색 (코사인 유사도)
   ↓
4. 상위 K개 결과 반환
```

---

## ⚠️ 알려진 이슈

### 1. Marker 텍스트 품질
**문제**: 일부 한글이 한자로 변환됨
```
营约机造 (잘못) → 협약체결 (정상)
```

**원인**: 
- PDF 폰트 인코딩 문제 추정
- Marker OCR 한글/한자 혼동

**영향**: 
- 검색 오염 (한자로 저장된 데이터는 검색/비교 불가)
- 서류 검토 봇에 치명적 — `营약机造`로 저장된 비목명은 기준 DB와 매칭 불가
- 표 구조는 보존되나 신뢰 불가

**해결 방안**:
- ~~Option A: MarkItDown과 비교 테스트~~ → **완료 (2026-03-18), 결과 아래 참고**
- Option B: Gemini PDF 직접 파싱 → **검토 중**
- ~~Option C: 한자 매핑 테이블~~ → 폐기 (근본 해결 아님)
- **현재**: Gemini 직접 파싱 테스트 전까지 보류

### 2. Marker 변환 속도
**문제**: CPU 모드로 매우 느림
- 2.1MB (약 14페이지): 14분 56초
- 38MB (516페이지): 2~5시간 예상

**원인**: VRAM 부족으로 GPU 사용 불가

**해결**: 없음 (하드웨어 제약)

### 3. 노이즈 패턴
**추가 발견**:
- HTML 태그 (`<mark>`, `<u>`) → 제거 중
- 이미지 참조 → 제거 중
- 깨진 괄호 → 제거 중

---

## 🎯 다음 단계

### 즉시 (우선순위 높음)
- [x] MarkItDown vs Marker 비교 테스트 → **완료 (2026-03-18)**
- [x] Gemini PDF 직접 파싱 테스트 → **완료 (2026-03-18)**
- [x] PDF 파싱 전략 확정 (Gemini File API) → **완료 (2026-03-19)**
- [x] app.py Gemini 전환 및 3개 문서 처리 → **완료 (2026-03-19)**
- [x] File API 전환, 배치 처리, 리포트 생성 추가 → **완료 (2026-03-19)**
- [x] Git 초기화 (모노레포, 노트북만) → **완료 (2026-03-19)**
- [x] /parse-toc, /convert-by-chapters 엔드포인트 구현 → **완료 (2026-03-30)**
  - 그리디 알고리즘으로 자동 분할 (100페이지 기준)
  - 장→절→부록 계층적 파싱, 중복 제거, fallback 로직
  - pypdf + markitdown 조합: MarkItDown으로 목차 파싱, pypdf로 분할, Gemini로 변환
  - requirements.txt에 pypdf==6.9.2, markitdown[pdf]==0.1.5 추가
- [ ] /parse-toc 테스트 (national_eval_rule.pdf) → **다음 작업**
- [ ] /convert-by-chapters 테스트 및 재처리
- [ ] RAG + Gemini 챗봇 (`/chat` 엔드포인트)

### 단기 (1~2주)
- [ ] 메타데이터 추출 (Gemini API → MongoDB)
- [ ] RAG + Gemini 챗봇 (`/chat` 엔드포인트)
- [ ] 영수증 OCR 검증 (`/validate-receipt`)
- [ ] 서류 자동 검증 (`/validate-document`)
- [ ] 통합 엔드포인트 (`/ask`)

### 중기 (1개월)
- [ ] 비목 마스터 데이터 완성 (JSON)
- [ ] 구비서류 체크리스트 DB 구축
- [ ] Late Chunking 테스트 (Jina v3 기능)
- [ ] Jina v5 A/B 테스트 (성능 비교)

### 장기 (추후)
- [ ] 프론트엔드 개발 (챗봇 UI)
- [ ] 사용자 인증/권한 관리
- [ ] 로그/모니터링 시스템
- [ ] API 문서 자동화 (Swagger)

---

## 📝 의사결정 기록

### 2026-03-17: Docker Compose + .env 환경변수 관리
**배경**: 환경변수 관리 방식 결정 필요

**옵션**:
1. `.env` 파일 (Docker Compose 표준)
2. `export` 명령어 (쉘 환경변수)
3. `docker run -e` (Docker CLI)
4. 시크릿 관리 도구 (Vault 등)

**결정**: Docker Compose + `.env` 파일

**이유**:
- 프로젝트가 이미 Docker 기반
- 보안성 (`.gitignore`로 제외)
- 확장성 (환경별 `.env.dev`, `.env.prod` 분리 가능)
- 재현성 (`.env.example`로 템플릿 공유)

### 2026-03-13: Marker CPU 모드 강제
**배경**: GPU + Marker 동시 실행 시 VRAM 부족

**옵션**:
1. Marker GPU 모드 (빠름, VRAM 부족)
2. Marker CPU 모드 (느림, 안정적)
3. GPU 메모리 최적화 (복잡)

**결정**: CPU 모드 강제 (`CUDA_VISIBLE_DEVICES=''`)

**이유**:
- 안정성 우선
- GPU는 임베딩 전용
- 속도는 감수

### 2026-03-10: MarkItDown → Marker 전환
**배경**: MarkItDown은 표 구조 손실

**결정**: Marker 사용 (당시)

**이유**:
- 표 구조가 핵심 정보 (집행 기준표 등)
- 속도는 감수
- 텍스트 노이즈는 후처리로 해결 (→ **이 가정이 틀렸음, 아래 참고**)

---

### 2026-03-18: MarkItDown vs Marker raw 비교 테스트 (ehwa_uni.pdf 기준)

**배경**: Qdrant 저장 데이터에서 한자 깨짐 확인 → 원인 규명 및 도구 재평가

**비교 결과** (노이즈 제거 없는 raw 결과물 기준):

| 항목 | MarkItDown | Marker |
|------|-----------|--------|
| 한글 텍스트 | ✅ 정상 | ❌ 한자 치환 (`营약机造`, `PLHIS`) |
| 표 구조 | ⚠️ 행 분리, 셀 내용 떠다님 | ⚠️ 셀 내부 단어 쪼개짐 (`<br>`) |
| 이미지 참조 | ✅ 없음 | ❌ `![](_page_X_Picture_Y.jpeg)` 다수 |
| cid 패턴 | ❌ `(cid:12873)` 잔존 | ✅ 없음 |
| 속도 | ⚡ ~5초 | 🐢 ~15분/2MB |
| 버그 | 없음 | PIL 객체가 markdown에 덤프됨 (text_from_rendered 반환값 오처리) |

**핵심 발견**:
- Marker 한글 깨짐은 **노이즈 제거로 해결 불가** — PDF 폰트 인코딩 단계에서 이미 잘못 변환됨
- 표 구조는 두 도구 모두 완벽하지 않음
- 서류 검토 봇 관점에서 한글 깨짐은 치명적 (비목명 매칭 불가)

**결론**: 두 도구 모두 단독으로는 부적합

**검토 중인 대안**:
- **Gemini PDF 직접 파싱** — 변환 도구 없이 PDF 원본을 Gemini Vision으로 직접 읽기
  - 장점: 한글 깨짐 없음, 표 구조 의미 해석 가능
  - 단점: 토큰 비용, 40MB 대용량 처리 전략 필요
- **역할 분리** — 텍스트는 MarkItDown(RAG용), 표는 Gemini(MongoDB용)
- **현재**: `ehwa_uni.pdf` 30페이지로 Gemini 직접 파싱 테스트 예정

---

## 📚 참고 자료

### 소스 문서
1. 창업탐색비_집행관리_가이드라인_2023.pdf (과학기술사업화진흥원)
2. 창업탐색팀_집행관리_가이드라인_2025_이화여대.pdf
3. 국가연구개발혁신법_매뉴얼.pdf (516페이지, 38MB)

### 기술 문서
- [Marker Documentation](https://github.com/VikParuchuri/marker)
- [Jina Embeddings](https://jina.ai/embeddings/)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

## 🔗 주요 엔드포인트

### 노트북 FastAPI (localhost:5000)
```
POST /convert-embed-store  # PDF → 벡터 저장
GET  /search               # 의미론적 검색
POST /detect-noise-patterns # Gemini 노이즈 감지
GET  /health               # 헬스체크
```

### 워크스테이션 서버 (100.88.194.30)
```
POST 100.88.194.30:5001/embed       # Jina v3 임베딩
POST 100.88.194.30:5002/convert-pdf # Marker 변환
```

### Qdrant (localhost:6333)
```
GET  localhost:6333/collections/documents
GET  localhost:6333/collections/documents/points/{id}
```

---

## 💡 트러블슈팅 히스토리

### apt Hash Sum mismatch (Docker 빌드 실패)
**증상**: 
```
E: Failed to fetch ... Hash Sum mismatch
Hashes of expected file: SHA256:6d43541d...
Hashes of received file: SHA256:2702b1ec...
```

**원인**:
1. Ubuntu 저장소 업데이트 타이밍 이슈 (가장 유력)
   - 저장소가 패키지 업데이트 중간에 빌드 시작
   - 파일 일부는 구버전, 일부는 신버전 다운로드
   - Hash 불일치 발생
2. Docker BuildKit 내부 캐시 손상
3. 네트워크 불안정 (패킷 손실)

**해결**:
```bash
# 1. BuildKit 캐시 완전 삭제
docker builder prune -af

# 2. 베이스 이미지 최신화 + 레이어 캐시 무시
docker-compose build --no-cache --pull
```

**상세 설명**:
- `docker builder prune -af`: BuildKit 내부 캐시 (패키지 목록, apt 인덱스) 완전 삭제
- `--no-cache`: Dockerfile 레이어 캐시 무시하고 모든 RUN 명령 재실행
- `--pull`: 베이스 이미지(pytorch/pytorch 등)를 최신으로 다시 다운로드

**캐시 종류별 비교**:
| 명령어 | BuildKit 캐시 | Dockerfile 캐시 | 베이스 이미지 |
|--------|--------------|----------------|--------------|
| `build` | 유지 | 사용 | 기존 사용 |
| `build --no-cache` | **유지** ⚠️ | 무시 | 기존 사용 |
| `build --no-cache --pull` | **유지** ⚠️ | 무시 | 최신 다운 |
| `prune -af` + `build --no-cache --pull` | **삭제** ✅ | 무시 | 최신 다운 | ← **완전 클린**

**핵심 개념**:
- `--no-cache`만으로는 BuildKit 내부 캐시가 남아있어 Hash mismatch 재발 가능
- `docker builder prune -af`로 내부 캐시까지 삭제해야 완전 해결

**발생일**: 2026-03-17

---

### VRAM 부족 (Marker + Jina 동시 실행)
**증상**: 3글자만 추출, CUDA error  
**해결**: Marker CPU 모드 강제

### Docker 네트워크 오류
**증상**: 컨테이너 재시작 시 네트워크 ID 불일치  
**해결**: `docker-compose down && docker network prune -f && docker-compose up -d`

### Marker 폰트 오류 (PermissionError)
**증상**: `/usr/local/lib/.../static` 쓰기 권한 없음  
**해결**: `os.environ['FONT_PATH'] = '/app/.fonts/GoNotoCurrent.ttf'`

### transformers 버전 충돌
**증상**: `all_tied_weights_keys` AttributeError  
**해결**: `transformers==4.44.2` 고정

---

## 👤 프로젝트 정보

**개발자**: 용사 (Elroilab, PE 엔지니어)  
**시작일**: 2026-03-05  
**환경**: Windows 11 + WSL2 + Docker Desktop  
**AI 어시스턴트**: Claude Sonnet 4.5

---

**마지막 작업**: Docker Hash Sum mismatch 해결 + 검색 기능 테스트 (2026-03-17)  
**다음 작업**: MarkItDown vs Marker 비교 테스트 (보류), 대용량 PDF 처리