import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import google.generativeai as genai

from config import (
    GEMINI_CONVERT_MODEL, GEMINI_CHAT_MODEL, GEMINI_CONFIG, qdrant_client,
    GEMINI_RECEIPT_EXTRACT_MODEL, GEMINI_RECEIPT_CLASSIFY_MODEL, GEMINI_RECEIPT_COMPLIANCE_MODEL,
)
from chunking import clean_markdown, select_and_chunk, filter_chunks, extract_section_title
from embeddings import embed_texts, delete_chunks_for_file, store_chunks, search

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
    print("[2/4] Cleaning markdown...")
    clean_content = clean_markdown(raw_markdown)

    # 3. 청킹 (Tier 2/3 자동 선택)
    print("[3/4] Chunking...")
    chunks, tier = select_and_chunk(clean_content)
    filtered = filter_chunks(chunks)
    print(f"  → {tier}: {len(chunks)} raw → {len(filtered)} filtered")

    # 4. 임베딩 + 저장
    print(f"[4/4] Embedding {len(filtered)} chunks via Jina cloud...")
    vectors = embed_texts(filtered, task="retrieval.passage")
    delete_chunks_for_file(filename)
    stored = store_chunks(filtered, vectors, filename)

    result = {
        "filename": filename,
        "file_size_mb": round(len(file_content) / (1024 * 1024), 1),
        "chunks_count": len(filtered),
        "vectors_stored": stored,
        "chunking_tier": tier,
        "embed_model": "jina-embeddings-v3",
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
            f"[문서 {i+1}] (출처: {p['source_file']} / {p.get('title','')}, score={hit.score:.3f})\n"
            f"{p['content']}"
        )
        sources.append({
            "score": round(hit.score, 4),
            "source_file": p["source_file"],
            "title": p.get("title", ""),
            "chunk_index": p.get("chunk_index"),
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
    search_query = f"{classification.get('main_category') or ''} {classification.get('sub_item') or ''} 사용기준".strip()
    sources = []
    context = ""
    if search_query:
        query_vector = embed_texts([search_query], task="retrieval.query")[0]
        hits = search(query_vector, top_k=top_k)
        context_blocks = []
        for i, hit in enumerate(hits):
            p = hit.payload
            context_blocks.append(
                f"[문서 {i+1}] (출처: {p['source_file']} / {p.get('title','')}, score={hit.score:.3f})\n"
                f"{p['content']}"
            )
            sources.append({
                "score": round(hit.score, 4),
                "source_file": p["source_file"],
                "title": p.get("title", ""),
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
