import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import google.generativeai as genai

from config import (
    GEMINI_CONVERT_MODEL, GEMINI_CHAT_MODEL, GEMINI_CONFIG, qdrant_client,
    GEMINI_RECEIPT_EXTRACT_MODEL, GEMINI_RECEIPT_CLASSIFY_MODEL, GEMINI_RECEIPT_COMPLIANCE_MODEL,
    GEMINI_DOC_MATCH_MODEL,
    GEMINI_DOC_TIER_MODEL, DEFAULT_DOC_TIER, get_doc_tier_override, build_doc_tier,
    SETTLEMENT_CAP_RULES, ABSOLUTE_CAP_RULES, PROHIBITION_MARKERS,
)
from chunking import clean_markdown, select_and_chunk, filter_chunks, extract_section_title
from embeddings import embed_texts, delete_chunks_for_file, store_chunks, search, get_stored_files, set_doc_tier_for_file

RECEIPT_MIME_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".pdf": "application/pdf",
}


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()

OUTPUT_DIR = Path("/app/manual/output")


def _log_raw_response(stage: str, text: str) -> None:
    """LLM 응답 원문을 파일로 남긴다 — 파싱 실패 시 모델이 틀렸는지 파서가 틀렸는지 구분하기 위함.
    로깅 실패가 기능을 막으면 안 되므로 예외는 전부 무시한다."""
    try:
        log_dir = OUTPUT_DIR / "raw_responses"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        (log_dir / f"{timestamp}_{stage}.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass


# ── PDF → Markdown ───────────────────────────────────────────

async def convert_pdf_to_markdown(file_content: bytes, filename: str) -> tuple[str, str]:
    """반환: (markdown_text, finish_reason). STOP=정상, MAX_TOKENS=잘림, 그 외(RECITATION 등)=내용 없음."""
    file_size_mb = len(file_content) / (1024 * 1024)
    print(f"📤 Uploading {filename} ({file_size_mb:.1f}MB) to Gemini File API...")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    uploaded = None
    try:
        uploaded = genai.upload_file(tmp_path, mime_type="application/pdf")
        response = GEMINI_CONVERT_MODEL.generate_content(
            [uploaded, "Convert this PDF to Markdown."],
            generation_config=GEMINI_CONFIG,
        )
        candidate = response.candidates[0] if response.candidates else None
        finish_reason = candidate.finish_reason.name if candidate else "UNKNOWN"

        if finish_reason not in ("STOP", "MAX_TOKENS"):
            print(f"⚠️ NO CONTENT ({finish_reason}): {filename} — Gemini가 콘텐츠를 반환하지 않음")
            return "", finish_reason

        markdown_text = response.text
        if finish_reason == "MAX_TOKENS":
            print(f"⚠️ TRUNCATED (MAX_TOKENS): {filename} — output cut off by Gemini output limit")
        print(f"✅ Gemini conversion done: {len(markdown_text):,} chars (finish_reason={finish_reason})")
        return markdown_text, finish_reason
    except Exception as e:
        raise RuntimeError(f"Gemini 변환 실패: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if uploaded:
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass


# ── 문서 등급 자동 분류 ───────────────────────────────────────

def classify_doc_tier(markdown_content: str, filename: str) -> dict:
    """문서 앞부분 내용을 보고 법적 위계(법률/시행령/시행규칙/고시/지침 등)를 자동 판정.
    수동 보정(DOCUMENT_TIER_OVERRIDE)이 있으면 그걸 우선 사용."""
    override = get_doc_tier_override(filename)
    if override:
        return override

    sample = markdown_content[:3000].strip()
    if not sample:
        return DEFAULT_DOC_TIER

    prompt = f"[파일명]\n{filename}\n\n[문서 앞부분]\n{sample}\n\n[지시] 이 문서의 법적 위계를 판정하라."
    try:
        resp = GEMINI_DOC_TIER_MODEL.generate_content(prompt, generation_config=GEMINI_CONFIG)
        result = json.loads(_strip_json_fence(resp.text))
        tier = result.get("tier") or "기타"
        doc_type = result.get("doc_type") or filename
        print(f"📑 doc_tier 분류: {filename} → {tier} ({doc_type})")
        return build_doc_tier(tier, doc_type)
    except Exception as e:
        print(f"⚠️ doc_tier 분류 실패({filename}): {e} — 기타(rank 99)로 폴백")
        return DEFAULT_DOC_TIER


async def reclassify_doc_tier(filename: str) -> dict:
    """이미 임베딩된 문서를 재임베딩 없이 재분류. OUTPUT_DIR에 저장된 변환 마크다운을 재사용."""
    md_path = OUTPUT_DIR / (Path(filename).stem + ".md")
    if not md_path.exists():
        raise RuntimeError(f"저장된 마크다운 없음: {md_path} (재변환 후 다시 시도)")
    content = md_path.read_text(encoding="utf-8")
    doc_tier = classify_doc_tier(content, filename)
    set_doc_tier_for_file(filename, doc_tier)
    return doc_tier


async def reclassify_all_doc_tiers() -> dict:
    results = {}
    for filename in get_stored_files():
        try:
            results[filename] = await reclassify_doc_tier(filename)
        except Exception as e:
            results[filename] = {"error": str(e)}
    return results


# ── 핵심 파이프라인 ───────────────────────────────────────────

async def process_pdf(file_content: bytes, filename: str, raw_markdown: str | None = None) -> dict:
    """
    PDF 처리 파이프라인.
    raw_markdown 제공 시 Gemini 변환 스킵 (재임베딩용).
    """
    # 1. 변환
    if raw_markdown is None:
        print(f"[1/4] Converting {filename}...")
        raw_markdown, _ = await convert_pdf_to_markdown(file_content, filename)
    else:
        print(f"[1/4] Skipping Gemini conversion (pre-converted)")

    # 변환 결과 저장 (품질 확인용)
    try:
        out = OUTPUT_DIR / (Path(filename).stem + ".md")
        out.write_text(raw_markdown, encoding="utf-8")
        print(f"💾 Markdown saved: {out}")
    except Exception as e:
        print(f"⚠️ Markdown save failed: {e}")

    # 2. 노이즈 제거
    print("[2/5] Cleaning markdown...")
    clean_content = clean_markdown(raw_markdown)

    # 3. 문서 등급 자동 분류 (법률/시행령/시행규칙/고시/지침)
    print("[3/5] Classifying doc tier...")
    doc_tier = classify_doc_tier(clean_content, filename)

    # 4. 청킹 (Tier 2/3 자동 선택)
    print("[4/5] Chunking...")
    chunks, tier = select_and_chunk(clean_content)
    filtered = filter_chunks(chunks)
    print(f"  → {tier}: {len(chunks)} raw → {len(filtered)} filtered")

    # 5. 임베딩 + 저장
    print(f"[5/5] Embedding {len(filtered)} chunks via Jina cloud...")
    vectors = embed_texts(filtered, task="retrieval.passage")
    delete_chunks_for_file(filename)
    stored = store_chunks(filtered, vectors, filename, doc_tier)

    result = {
        "filename": filename,
        "file_size_mb": round(len(file_content) / (1024 * 1024), 1),
        "chunks_count": len(filtered),
        "vectors_stored": stored,
        "chunking_tier": tier,
        "embed_model": "jina-embeddings-v3",
        "doc_tier": doc_tier["tier"],
        "doc_tier_label": doc_tier["label"],
    }

    try:
        _update_report(result)
    except Exception as e:
        print(f"⚠️ Report update failed: {e}")

    return result


# ── RAG Q&A ──────────────────────────────────────────────────

async def chat(query: str, top_k: int = 5) -> dict:
    query_vector = embed_texts([query], task="retrieval.query")[0]
    hits = search(query_vector, top_k=top_k)

    if not hits:
        return {"query": query, "answer": "참고 문서에서 검색 결과가 없습니다.", "sources": []}

    context_blocks = []
    sources = []
    for i, hit in enumerate(hits):
        p = hit.payload
        context_blocks.append(
            f"[문서 {i+1}] (출처: {p['source_file']} [{p.get('doc_tier_label', '미분류 문서')}] / {p.get('title','')}, score={hit.score:.3f})\n"
            f"{p['content']}"
        )
        sources.append({
            "score": round(hit.score, 4),
            "source_file": p["source_file"],
            "title": p.get("title", ""),
            "chunk_index": p.get("chunk_index"),
            "doc_tier": p.get("doc_tier", "unknown"),
            "doc_tier_label": p.get("doc_tier_label", "미분류 문서"),
        })

    context = "\n\n---\n\n".join(context_blocks)
    prompt = (
        f"[참고 문서]\n{context}\n\n"
        f"[질문]\n{query}\n\n"
        "[지시] 위 참고 문서만 근거로 답하라. 문서에 없으면 없다고 말하라. 답변 끝에 근거 출처를 표기하라."
    )
    response = GEMINI_CHAT_MODEL.generate_content(prompt, generation_config=GEMINI_CONFIG)
    return {"query": query, "answer": response.text, "sources": sources}


# ── 영수증 비목분류 ──────────────────────────────────────────

async def _match_supporting_documents(
    required_documents: list[str],
    supporting_docs: list[tuple[bytes, str]] | None,
) -> list[dict]:
    """필요서류 목록과 첨부 증빙파일들을 LLM 1회 호출로 대조한다(M×N 루프 금지 — 모델이
    전체를 보고 배타적으로 배정하게 함). supporting_docs 없으면 매칭 자체를 스킵([]),
    required_documents가 없으면 그와 구분되는 별도 신호("(필요서류 목록 없음)" 1건)를 반환한다."""
    if not supporting_docs:
        return []

    if not required_documents:
        return [{
            "document": "(필요서류 목록 없음)",
            "status": "unclear",
            "evidence_file": None,
            "confidence": "low",
            "reason": "컴플라이언스 단계가 필요서류를 특정하지 못해 매칭을 수행할 수 없음",
        }]

    tmp_paths = []
    uploaded_files = []
    try:
        file_parts = []
        filename_lines = []
        for i, (content, filename) in enumerate(supporting_docs):
            suffix = Path(filename).suffix.lower() or ".jpg"
            mime_type = RECEIPT_MIME_TYPES.get(suffix, "image/jpeg")
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(content)
                tmp_paths.append(tmp.name)
            uploaded = genai.upload_file(tmp.name, mime_type=mime_type)
            uploaded_files.append(uploaded)
            file_parts.append(uploaded)
            filename_lines.append(f"{i+1}. {filename}")

        match_prompt = (
            "[필요서류 목록]\n" + "\n".join(f"- {d}" for d in required_documents) + "\n\n"
            "[첨부 파일]\n" + "\n".join(filename_lines) + "\n\n"
            "[지시] 위 필요서류 각각에 대해 첨부 파일 중 해당하는 것을 판정하라."
        )
        match_resp = GEMINI_DOC_MATCH_MODEL.generate_content(
            [*file_parts, match_prompt], generation_config=GEMINI_CONFIG,
        )
        _log_raw_response("doc_match", match_resp.text)
        parsed = json.loads(_strip_json_fence(match_resp.text))
        if "document_match" not in parsed:
            raise ValueError("document_match 키 없음")
        return parsed["document_match"]
    except Exception as e:
        return [{
            "document": d, "status": "unclear", "evidence_file": None,
            "confidence": "low", "reason": f"증빙서류 매칭 처리 중 오류: {e}",
        } for d in required_documents]
    finally:
        for p in tmp_paths:
            if os.path.exists(p):
                os.unlink(p)
        for uploaded in uploaded_files:
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass


def check_absolute_cap(
    sub_item: str, amount: int | float,
    grade: str | None = None, region: str | None = None, days: int = 1,
) -> dict:
    """ABSOLUTE_CAP_RULES 기준 결정론적 절대금액 판정. LLM에 묻지 않는다 — 금액 오독은 치명적.
    sub_item이 등록된 규칙 어느 것과도 정확히 일치하지 않으면(세부항목 불명확 포함) unknown을
    반환한다 — 모르면 모른다고 하지, 아무 규칙이나 들이대 오탐을 만들지 않는다.
    grade가 grade_dependent 규칙에서 None이면 가장 관대한 등급(rule["default_grade"])으로
    판정한다 — false negative는 감수하되 false positive는 만들지 않기 위함.
    region은 현재 구현된 규칙(#2/#3/#6/#7) 중 쓰는 게 없다(지역별 캡인 #8 숙박비는 미구현,
    이유는 ABSOLUTE_CAP_RULES 옆 주석 참고) — 향후 규칙 확장 대비 시그니처만 유지."""
    rule = next((r for r in ABSOLUTE_CAP_RULES if sub_item in r["sub_items"]), None)
    if rule is None:
        return {
            "status": "unknown", "rule": None, "limit": None, "actual": amount,
            "reason": f"'{sub_item}'에 대한 절대금액 규칙 없음(미구현이거나 세부항목 특정 불가)",
            "citation": None,
        }

    if rule["grade_dependent"]:
        g = grade or rule["default_grade"]
        if g not in rule["limits"]:
            return {
                "status": "unknown", "rule": rule["label"], "limit": None, "actual": amount,
                "reason": f"등급 값 '{g}'이 이 규칙의 등급 구간({list(rule['limits'])})에 없음",
                "citation": f"{rule['source']['location']} — \"{rule['source']['quote']}\"",
            }
        limit = rule["limits"][g]
    else:
        limit = rule["limits"]["ALL"]

    if rule["unit"] in ("1일", "1박"):
        limit = limit * max(days or 1, 1)

    citation = f"{rule['source']['location']} — \"{rule['source']['quote']}\""
    if rule["type"] == "금지형":
        status = "violation" if amount > limit else "ok"
        reason = f"{rule['label']} {limit:,.0f}원 {'초과' if status == 'violation' else '이내'} — 실제 {amount:,.0f}원"
    else:  # 절차형
        status = "review" if amount >= limit else "ok"
        reason = f"{rule['label']} {limit:,.0f}원 {'이상 — 심의위원회 회부 대상' if status == 'review' else '미만'} — 실제 {amount:,.0f}원"

    return {
        "status": status, "rule": rule["label"], "limit": limit, "actual": amount,
        "reason": reason, "citation": citation,
    }


async def classify_receipt(
    file_content: bytes, filename: str, top_k: int = 5,
    supporting_docs: list[tuple[bytes, str]] | None = None,
) -> dict:
    suffix = Path(filename).suffix.lower() or ".jpg"
    mime_type = RECEIPT_MIME_TYPES.get(suffix, "image/jpeg")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    uploaded = None
    try:
        # 1. 영수증 정보 추출 (Gemini vision)
        uploaded = genai.upload_file(tmp_path, mime_type=mime_type)
        extract_resp = GEMINI_RECEIPT_EXTRACT_MODEL.generate_content(
            [uploaded, "이 영수증/증빙 이미지에서 정보를 추출하라."],
            generation_config=GEMINI_CONFIG,
        )
        try:
            extracted = json.loads(_strip_json_fence(extract_resp.text))
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(f"영수증 정보 추출 실패 (JSON 파싱 오류): {e}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"영수증 이미지 처리 실패: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if uploaded:
            try:
                genai.delete_file(uploaded.name)
            except Exception:
                pass

    if extracted.get("is_receipt") is False:
        return {"extracted": extracted, "classification": None, "compliance": None, "sources": []}

    # 2. 비목 분류 (고정 목록 기반, RAG 없이 직접 판정 — 목록이 작고 완결돼있어 검색보다 안정적)
    classify_prompt = (
        f"[영수증 정보]\n"
        f"- 항목: {extracted.get('item')}\n"
        f"- 상호: {extracted.get('vendor')}\n"
        f"- 금액: {extracted.get('amount')}원\n"
        f"- 날짜: {extracted.get('date')}\n\n"
        "[지시] 위 영수증이 비목 목록 중 어디에 해당하는지 판단하라."
    )
    classify_resp = GEMINI_RECEIPT_CLASSIFY_MODEL.generate_content(classify_prompt, generation_config=GEMINI_CONFIG)
    try:
        classification = json.loads(_strip_json_fence(classify_resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"비목 판정 실패 (JSON 파싱 오류): {e}")

    # 3. 컴플라이언스 검토 (분류된 비목명으로 타겟 RAG 검색 — 법률용어 대 법률용어라 score 안정적)
    # flag=지원불가면 main_category/sub_item이 "해당없음"이라 그걸로 검색하면 무의미함 —
    # 대신 지원불가 근거(금지 조항) 자체를 검색어로 써서 컴플라이언스 단계가 인용할 근거를 확보한다.
    # "한도/사용기준"과 "제출서류"를 한 쿼리에 섞으면 그 두 단어가 각자 다른 참고표(불인정기준 표 vs
    # 제출서류 표)를 무관하게 끌어올려서 서로를 오염시킨다 — 목적별로 분리해 검색한다.
    if classification.get("flag") == "지원불가":
        # flag=지원불가면 sub_item이 "해당없음"이라 검색 재료가 없다.
        # taxonomy의 금지 목록이 유한·고정이므로 쿼리도 고정으로 둔다.
        # item(LLM 출력)을 쓰면 단일 실패점이 하나 늘고, 단독으로는 조항을 못 끌어온다(측정함).
        queries = [
            "국내여비 유류비 렌터카 주차비 청구 불가",
            "회의비 현물성 물품 구매 지급 불가 불인정기준",
        ]
    else:
        sub_item = classification.get('sub_item') or ''
        queries = [
            f"{sub_item} 한도 사용기준",
            f"{sub_item} 제출서류",
        ]
    sources = []
    context = ""
    if any(queries):
        per_query_k = -(-top_k // len(queries)) + 1  # 올림 나눗셈 — 쿼리 개수(1개/2개)에 맞춰 스케일
        seen = {}
        for q in queries:
            query_vector = embed_texts([q], task="retrieval.query")[0]
            for hit in search(query_vector, top_k=per_query_k):
                if hit.id not in seen or hit.score > seen[hit.id].score:
                    seen[hit.id] = hit
        hits = sorted(seen.values(), key=lambda h: h.score, reverse=True)[:top_k]
        context_blocks = []
        for i, hit in enumerate(hits):
            p = hit.payload
            context_blocks.append(
                f"[문서 {i+1}] (출처: {p['source_file']} [{p.get('doc_tier_label', '미분류 문서')}] / {p.get('title','')}, score={hit.score:.3f})\n"
                f"{p['content']}"
            )
            sources.append({
                "score": round(hit.score, 4),
                "source_file": p["source_file"],
                "title": p.get("title", ""),
                "doc_tier": p.get("doc_tier", "unknown"),
                "doc_tier_label": p.get("doc_tier_label", "미분류 문서"),
            })
        context = "\n\n---\n\n".join(context_blocks)

    compliance_prompt = (
        f"[영수증 정보]\n"
        f"- 항목: {extracted.get('item')} / 상호: {extracted.get('vendor')} / "
        f"금액: {extracted.get('amount')}원 / 날짜: {extracted.get('date')}\n\n"
        f"[분류 결과]\n{classification.get('main_category')} > {classification.get('sub_item')} "
        f"(flag: {classification.get('flag')})\n\n"
        f"[참고 규정]\n{context or '(검색된 규정 없음)'}\n\n"
        "[지시] 위 분류가 참고 규정의 사용기준(한도/필요서류/절차)에 맞게 집행됐는지 검토하라."
    )
    compliance_resp = GEMINI_RECEIPT_COMPLIANCE_MODEL.generate_content(compliance_prompt, generation_config=GEMINI_CONFIG)
    try:
        compliance = json.loads(_strip_json_fence(compliance_resp.text))
    except (json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"컴플라이언스 검토 실패 (JSON 파싱 오류): {e}")

    # 2-1. 컴플라이언스가 발견한 명시적 금지를 분류 단계로 역전파(override)
    # LLM이 "제출서류 표" 등을 금지 조항으로 오인해 override를 낼 수 있어(r011 사례),
    # citation에 PROHIBITION_MARKERS가 실제로 있을 때만 인정한다 — 문자열 검사는
    # LLM 판단이 아니라 코드로 확정할 수 있는 사실이므로 게이트한다.
    if compliance.get("override_flag") == "지원불가":
        if classification.get("flag") == "지원불가":
            # 분류 단계가 이미 지원불가 — override는 뒤집는 게 아니라 재확인(Rule 0)이므로 게이트 불필요
            compliance["override_noop"] = "flag 변화 없음 — 게이트 미적용"
        else:
            citation = compliance.get("citation") or ""
            if any(marker in citation for marker in PROHIBITION_MARKERS):
                classification["flag_before_override"] = classification.get("flag")
                classification["override_reason"] = citation
                classification["flag"] = "지원불가"
                classification["main_category"] = "해당없음"
                classification["sub_item"] = "해당없음"
            else:
                compliance["override_rejected"] = f"citation에 금지 표현 없음 — 게이트 차단: {citation!r}"
                if compliance.get("compliance_status") == "위반의심":
                    compliance["status_before_gate"] = compliance["compliance_status"]
                    compliance["compliance_status"] = "확인불가"

    # 3-1. 절대금액 캡 결정론적 판정 (LLM 판단과 별개 — 금액은 코드가 직접 계산)
    # grade/region은 현재 추출 단계가 뽑지 않으므로 항상 None으로 넘긴다 — LLM에게
    # 추론시키지 않고, 없는 채로 보수적으로(가장 관대한 등급 기본값) 판정한다.
    compliance["absolute_cap"] = check_absolute_cap(
        sub_item=classification.get("sub_item") or "",
        amount=extracted.get("amount") or 0,
    )

    # 4. 증빙서류 첨부 여부 매칭 (supporting_docs 있을 때만 수행)
    compliance["document_match"] = await _match_supporting_documents(
        compliance.get("required_documents") or [], supporting_docs
    )

    return {
        "extracted": extracted,
        "classification": classification,
        "compliance": compliance,
        "sources": sources,
    }


# ── 정산보고서 일괄 검토 ─────────────────────────────────────

def _check_settlement_caps(category_totals: dict, sub_item_totals: dict, total_budget: int) -> list[dict]:
    """SETTLEMENT_CAP_RULES 기준으로 비목별 계상비율 캡 초과 여부 검증."""
    violations = []
    for rule in SETTLEMENT_CAP_RULES:
        source = sub_item_totals if rule["scope"] == "sub_item" else category_totals
        amount = sum(source.get(k, 0) for k in rule["keys"])
        ratio = amount / total_budget if total_budget else 0
        exceeded = ratio < rule["ratio"] if rule["type"] == "min" else ratio > rule["ratio"]
        if exceeded:
            violations.append({
                "rule": rule["label"],
                "keys": rule["keys"],
                "type": rule["type"],
                "threshold_ratio": rule["ratio"],
                "actual_ratio": round(ratio, 4),
                "actual_amount": amount,
            })
    return violations


async def review_settlement(files: list[tuple[bytes, str]], total_budget: int | None = None, top_k: int = 5) -> dict:
    """정산보고서(영수증 여러 건) 일괄 검토. 각 영수증은 classify_receipt() 로직을 그대로 재사용.
    total_budget 제공 시에만 비목별 계상비율 캡(SETTLEMENT_CAP_RULES) 검증."""
    lines = []
    failed = []
    for content, filename in files:
        try:
            result = await classify_receipt(content, filename, top_k=top_k)
            lines.append({"filename": filename, **result})
        except RuntimeError as e:
            failed.append({"filename": filename, "error": str(e)})

    category_totals: dict[str, int] = {}
    sub_item_totals: dict[str, int] = {}
    for line in lines:
        if line["classification"] is None:  # is_receipt=false — 집계 제외
            continue
        amount = line["extracted"].get("amount") or 0
        main_category = line["classification"].get("main_category") or "해당없음"
        sub_item = line["classification"].get("sub_item") or "해당없음"
        category_totals[main_category] = category_totals.get(main_category, 0) + amount
        sub_item_totals[sub_item] = sub_item_totals.get(sub_item, 0) + amount

    cap_violations = []
    if total_budget:
        cap_violations = _check_settlement_caps(category_totals, sub_item_totals, total_budget)

    flagged_count = sum(1 for line in lines if line["classification"] and line["classification"].get("flag") == "지원불가")
    violation_count = sum(1 for line in lines if line["compliance"] and line["compliance"].get("compliance_status") == "위반의심")

    return {
        "lines": lines,
        "failed": failed,
        "category_totals": category_totals,
        "sub_item_totals": sub_item_totals,
        "total_budget": total_budget,
        "cap_violations": cap_violations,
        "summary": {
            "total_lines": len(lines),
            "failed_lines": len(failed),
            "flagged_disallowed": flagged_count,
            "compliance_violations": violation_count,
            "cap_violations": len(cap_violations),
        },
    }


# ── 리포트 ───────────────────────────────────────────────────

def _update_report(result: dict) -> None:
    report_path = OUTPUT_DIR / "processing_report.md"
    records = {}
    if report_path.exists():
        for line in report_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("| 파일명") and not line.startswith("| ---"):
                parts = [p.strip() for p in line.strip("| ").split("|")]
                if len(parts) >= 4:
                    records[parts[0]] = parts

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    records[result["filename"]] = [result["filename"], result.get("file_size_mb", "-"),
                                   str(result["chunks_count"]), now, "✅"]
    total = sum(int(r[2]) for r in records.values() if r[2].isdigit())

    lines = [
        "# PDF 처리 현황 보고서", f"최종 업데이트: {now}", "",
        "## 전체 요약", "| 항목 | 값 |", "|------|-----|",
        f"| 총 문서 수 | {len(records)} |", f"| 총 청크 수 | {total:,} |",
        f"| 마지막 처리 | {result['filename']} |", "",
        "## 문서별 상세", "| 파일명 | 청크 수 | 처리 일시 | 상태 |", "|--------|---------|-----------|------|",
    ]
    for r in sorted(records.values(), key=lambda x: x[0]):
        lines.append(f"| {r[0]} | {r[2]} | {r[3]} | {r[4]} |")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"📊 Report updated: {report_path}")
