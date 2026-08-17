import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import google.generativeai as genai

from config import (
    GEMINI_CONVERT_MODEL, GEMINI_CHAT_MODEL, GEMINI_CONFIG, qdrant_client,
    GEMINI_RECEIPT_EXTRACT_MODEL, GEMINI_RECEIPT_CLASSIFY_MODEL, GEMINI_RECEIPT_COMPLIANCE_MODEL,
    GEMINI_DOC_TIER_MODEL, DEFAULT_DOC_TIER, get_doc_tier_override, build_doc_tier,
    SETTLEMENT_CAP_RULES,
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

async def classify_receipt(file_content: bytes, filename: str, top_k: int = 5) -> dict:
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
    if classification.get("flag") == "지원불가":
        search_query = "회의비 현물성 물품 구매 지급 불가 규정 제출서류 불인정기준"
    else:
        search_query = (
            f"{classification.get('main_category') or ''} {classification.get('sub_item') or ''} "
            "사용기준 제출서류 불인정기준"
        ).strip()
    sources = []
    context = ""
    if search_query:
        query_vector = embed_texts([search_query], task="retrieval.query")[0]
        hits = search(query_vector, top_k=top_k)
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
        amount = line["extracted"].get("amount") or 0
        main_category = line["classification"].get("main_category") or "해당없음"
        sub_item = line["classification"].get("sub_item") or "해당없음"
        category_totals[main_category] = category_totals.get(main_category, 0) + amount
        sub_item_totals[sub_item] = sub_item_totals.get(sub_item, 0) + amount

    cap_violations = []
    if total_budget:
        cap_violations = _check_settlement_caps(category_totals, sub_item_totals, total_budget)

    flagged_count = sum(1 for line in lines if line["classification"].get("flag") == "지원불가")
    violation_count = sum(1 for line in lines if line["compliance"].get("compliance_status") == "위반의심")

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
