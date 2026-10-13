# FINDINGS — `/chat` end-to-end 가동 + 검색 품질 원인 분리

> 세션: 2026-06-25
> 맥락: PROJECT_STATUS.md 우선순위 #1(`/chat` 최소 구현) 착수 → 동작 확인 → 안티패턴 #2(답변 오류 원인 분리) 수행 결과

---

## 0. 한 줄 결론

`/chat` end-to-end **가동 성공**(첫 마일스톤). 검색 품질 약점의 진짜 원인은 **임베딩 task가 아니라 청킹 regex 버그**로 분리됨. 부수로 중복 적재 발견. 둘 다 collection 재구축으로 해결.

---

## 1. 이번 세션 한 일

- 죽은 GPU 임베딩 서버(Jina v3, `100.88.194.30:5001`) → **Jina cloud API**로 교체 (`jina_embed()` 헬퍼).
  - 기존 Qdrant 1341 chunks = local Jina v3(1024-dim, Cosine)로 박힘 → 동일 모델 cloud로 query 임베딩해야 정합. 재임베딩 없이 재사용 목적.
- `/chat` 엔드포인트 신규: query 임베딩(Jina) → Qdrant 검색 → 검색 chunk 근거로 Gemini 답변(+출처).
- `/search`도 같은 헬퍼로 교체 + `task` 파라미터(디버그용) 추가.
- docker-compose에 `JINA_API_KEY` 주입.

---

## 2. 동작 확인 (마일스톤)

질문: `학생인건비는 어떤 용도로 쓸 수 있나?`

- 파이프라인 전 구간 작동. Gemini 근거기반 답변, 환각 없음, 없는 내용은 "참고 문서에서 찾을 수 없습니다"로 정직하게 거절.
- **프롬프트 계층 = 양호.** 원인 후보(청킹/검색/프롬프트) 중 프롬프트는 제외.

---

## 3. 임베딩 task 비교 실험

동일 질문을 task 4종으로 검색 → top score 비교:

| task | top score | 해석 |
|---|---|---|
| `retrieval.query` | 0.524 | 현재 설정 |
| `retrieval.passage` | 0.119 | 바닥 |
| `text-matching` | 0.47 | — |
| `separation` | 0.639 | 함정(높지만 무의미) |

**판독:**
- 모든 task에서 **같은 chunk(학생연구자 정의)가 1등** → task 바꿔도 제대로 된 chunk가 안 나옴. 순위 안 바뀜.
- Jina v3 비대칭쌍 규칙: 문서=`retrieval.passage` 저장 / query=`retrieval.query` 조회가 정답쌍. 관측(query 0.524 ↔ passage 0.119 바닥)이 정확히 이 패턴 → **passages는 `retrieval.passage`로 박혀 있음**. 즉 현재 query task(`retrieval.query`)는 **이미 옳다.**
- `separation` 0.639는 함정: 대칭 task를 비대칭 저장공간에 섞어 절댓값만 부풀린 것. 잡힌 chunk도 동일하게 틀린 것이라 무의미.

**결론: 검색 약점은 task 미스매치 아님.**

---

## 4. 진짜 원인 — 청킹 regex 버그 (HIGH)

`chunk_by_heading()` (app.py:207) 의 절 분할 regex:

```python
r'(?=^제\d+[장절]\s)'   # "제4절 " 기대. 그러나 Gemini 출력은 "# 제4절 ..."
```

Gemini가 모든 절을 markdown heading `# 제N절`로 출력하는데, regex는 줄 맨앞 `제`를 기대 → **`# ` prefix 때문에 절 경계가 하나도 안 잡힘**.

영향:
- heading 기반 청킹이 **조용히 실패** → 전부 fallback(1500자 단순 분할)로 추락.
- chunk 경계가 절(의미 단위)과 어긋남 → 검색 정밀도 전반 저하.
- 같은 버그가 `remove_table_of_contents()`, `extract_section_title()` 에도 있을 가능성 높음(동일하게 `#` prefix 미고려). TOC가 chunk로 남는 현상(chunk 0,1,2 = 목차)도 이걸로 설명됨.

**수정 방향:** 절/장 패턴 앞에 markdown heading prefix 허용 → `r'(?=^#{0,6}\s*제\d+[장절]\s)'` 형태. (단, regex 무검증 변경 = 안티패턴 #3 → 수정 전후 chunk 수/경계 비교 후 적용.)

---

## 5. 이 질문(학생인건비)은 원문 자체가 얇음

- 제4절 학생인건비 (national_eval_rule.md:2005~2011): `## 가. 사용용도` 밑에 **용도 리스트 없이 "학생연구자 정의"만** 존재. 다른 절(제5~12절)은 `[XXX 사용용도] - 항목…` 식 용도 리스트 보유.
- 즉 이 질문에 한해 검색·답변 모두 원문에 충실. 실제 학생인건비 상세 기준은 제3장 인건비 절 또는 표에 분산된 것으로 추정.
- **데모용 질문으로 학생인건비는 부적합** → 용도 리스트가 풍부한 항목(연구활동비/출장비/회의비 등)으로 데모 질문 선정 권장.

---

## 6. 중복 적재 (MEDIUM)

- `/chat` sources에서 `chunk_index 151` 2회, `153` 2회 동일 등장 → national_eval_rule.pdf가 **2번 적재됨**.
- points_count 1341은 중복 포함 부풀린 값.
- top_k 슬롯 낭비로 검색 품질 직접 저하.

---

## 7. 다음 액션 (권장 순서)

1. **청킹 regex 버그 수정** — markdown heading prefix 허용. 수정 전후 chunk 경계 비교(안티패턴 #3 준수).
2. **collection 재구축** — 중복 제거 + 새 청킹으로 재적재. 이때 임베딩은 Jina cloud `retrieval.passage`로 통일(재현성, PROJECT_STATUS #4 충족). `process_pdf`의 임베딩 호출부도 `jina_embed(..., task="retrieval.passage")`로 교체 필요(현재 죽은 GPU 서버 호출 그대로 남아있음).
3. **데모 질문 5개 재선정** — 용도 리스트 풍부한 항목 중심.
4. 재구축 후 `/chat` 재검증 → score 상승 확인.

---

## 8. 미해결 / 메모

- `process_pdf()`(app.py:400 부근) 임베딩 호출은 아직 죽은 `EMBEDDING_SERVER` 그대로 → 신규 적재 시 실패함. 재구축 작업에서 같이 교체.
- `.env`에 GEMINI/JINA 실 API 키 평문. git 추적 여부 확인 + 추적 시 `.gitignore`+키 회전 필요(보안).
