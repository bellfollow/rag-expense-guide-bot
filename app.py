import json
import os
import re
import tempfile
from pathlib import Path

import google.generativeai as genai
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from chunking import detect_chunking_tier, extract_first_pages_text
from embeddings import get_stored_files, init_collection
from pipeline import chat as pipeline_chat
from pipeline import classify_receipt as pipeline_classify_receipt
from pipeline import review_settlement as pipeline_review_settlement
from pipeline import convert_pdf_to_markdown, process_pdf

app = FastAPI(title="AI 연구비 집행 챗봇 서버")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup_event():
    init_collection()


# ── 헬스 ─────────────────────────────────────────────────────

@app.get("/")
def root():
    from fastapi.responses import FileResponse
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── 임베딩 파이프라인 ─────────────────────────────────────────

@app.post("/convert-embed-store")
async def convert_embed_store(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다")
    try:
        content = await file.read()
        result = await process_pdf(content, file.filename)
        return {"status": "success", **result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파이프라인 처리 중 오류: {e}")


@app.post("/convert-embed-store-batch")
async def convert_embed_store_batch(folder_path: str):
    from pathlib import Path
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"폴더를 찾을 수 없습니다: {folder_path}")

    pdf_files = list(folder.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(status_code=400, detail="폴더에 PDF 파일이 없습니다")

    stored = get_stored_files()
    processed, skipped, failed = [], [], []

    for pdf_path in sorted(pdf_files):
        filename = pdf_path.name
        if filename in stored:
            skipped.append(filename)
            continue
        try:
            content = pdf_path.read_bytes()
            result = await process_pdf(content, filename)
            processed.append(result)
        except Exception as e:
            failed.append({"filename": filename, "error": str(e)})

    return {"status": "success", "total_files": len(pdf_files),
            "processed": processed, "skipped": skipped, "failed": failed}


@app.post("/embed-from-markdown")
async def embed_from_markdown(filename: str):
    from pathlib import Path
    md_path = Path("/app/manual/output") / (Path(filename).stem + ".md")
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"Markdown 파일 없음: {md_path}")
    raw_markdown = md_path.read_text(encoding="utf-8")
    try:
        result = await process_pdf(b"", filename, raw_markdown=raw_markdown)
        return {"status": "success", **result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ── TOC 기반 Tier 1 파이프라인 ───────────────────────────────

@app.post("/parse-toc")
async def parse_toc(file: UploadFile = File(...)):
    from markitdown import MarkItDown
    from pathlib import Path
    from pypdf import PdfReader
    CHAR_BUDGET = 50000  # gemini-3.5-flash output 65536 tokens(~1.4자/토큰) 대비 46% 여유
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            reader = PdfReader(tmp_path)
            total_pages = len(reader.pages)
            raw_text = MarkItDown().convert(tmp_path).text_content

            # offset 자동 계산
            offset = 0
            marker_match = re.search(r'[/\\]\s*(\d+)\s*[/\\]', raw_text)
            if marker_match:
                doc_page = int(marker_match.group(1))
                pdf_pat = re.compile(r'[/\\]\s*' + str(doc_page) + r'\s*[/\\]')
                for i, page in enumerate(reader.pages):
                    if pdf_pat.search(page.extract_text() or ""):
                        offset = (i + 1) - doc_page
                        break

            chapters_raw = [
                {"chapter": int(m.group(1)), "title": m.group(2).strip(), "start_page": int(m.group(3))}
                for m in re.finditer(r'제(\d+)장\s+([^\n·]+?)\s+[·\s·]+\s*(\d+)\s*$', raw_text, re.MULTILINE)
            ]
            seen: set = set()
            chapters_raw = [
                ch for ch in chapters_raw
                if (ch["chapter"], ch["start_page"]) not in seen
                and not seen.add((ch["chapter"], ch["start_page"]))
            ]

            sections_raw = [
                {"section": int(m.group(1)), "title": m.group(2).strip(), "start_page": int(m.group(3))}
                for m in re.finditer(r'제(\d+)절\s+([^\n·]+?)\s+[·\s·]+\s*(\d+)\s*$', raw_text, re.MULTILINE)
            ]
            seen = set()
            sections_raw = [
                s for s in sections_raw
                if (s["section"], s["start_page"]) not in seen
                and not seen.add((s["section"], s["start_page"]))
            ]

            appendix_start = raw_text.find('[부록]')
            appendix_items = []
            if appendix_start != -1:
                for m in re.finditer(r'^(\d+)\.\s+([^\n·]+?)\s+[·\s·]+\s*(\d+)\s*$',
                                     raw_text[appendix_start:], re.MULTILINE):
                    page = int(m.group(3))
                    if page >= 300:
                        appendix_items.append({"number": int(m.group(1)),
                                               "title": m.group(2).strip(), "start_page": page})
            seen = set()
            appendix_items = [
                a for a in appendix_items
                if a["start_page"] not in seen and not seen.add(a["start_page"])
            ]
            for i, a in enumerate(appendix_items):
                a["end_page"] = appendix_items[i+1]["start_page"] - 1 if i+1 < len(appendix_items) else total_pages

            appendix_first = appendix_items[0]["start_page"] if appendix_items else total_pages
            for i, ch in enumerate(chapters_raw):
                ch["end_page"] = chapters_raw[i+1]["start_page"] - 1 if i+1 < len(chapters_raw) else appendix_first - 1

            def estimate_chars(start_doc_page: int, end_doc_page: int) -> int:
                # start/end_doc_page는 TOC상 문서 쪽번호. 실제 물리 PDF 페이지는 offset 보정 필요.
                lo = max(start_doc_page + offset - 1, 0)
                hi = min(end_doc_page + offset, total_pages)
                if lo >= hi:
                    return 0
                return sum(len(reader.pages[i].extract_text() or "") for i in range(lo, hi))

            def bisect_by_budget(start_doc_page: int, end_doc_page: int, budget: int):
                if start_doc_page >= end_doc_page:
                    return [(start_doc_page, end_doc_page)]
                if estimate_chars(start_doc_page, end_doc_page) <= budget:
                    return [(start_doc_page, end_doc_page)]
                mid = (start_doc_page + end_doc_page) // 2
                return bisect_by_budget(start_doc_page, mid, budget) + bisect_by_budget(mid + 1, end_doc_page, budget)

            def pack_by_budget(items: list, budget: int, label_prefix: str) -> list:
                # 예산 초과 단일 항목은 페이지 이분(bisect)으로 먼저 쪼갠 뒤, 작은 항목끼리는 그리디로 합침
                expanded = []
                for it in items:
                    if estimate_chars(it["start_page"], it["end_page"]) <= budget:
                        expanded.append(it)
                    else:
                        for sp, ep in bisect_by_budget(it["start_page"], it["end_page"], budget):
                            expanded.append({**it, "start_page": sp, "end_page": ep})

                groups, cur, cur_chars = [], [], 0
                for it in expanded:
                    c = estimate_chars(it["start_page"], it["end_page"])
                    if cur and cur_chars + c > budget:
                        groups.append(cur); cur, cur_chars = [it], c
                    else:
                        cur.append(it); cur_chars += c
                if cur:
                    groups.append(cur)

                result = []
                for idx, group in enumerate(groups):
                    suffix = f"-{idx+1}" if len(groups) > 1 else ""
                    title = group[0]["title"] if len(group) == 1 else f"{group[0]['title']} ~ {group[-1]['title']}"
                    result.append({
                        "label": f"{label_prefix}{suffix}", "title": title,
                        "start_page": group[0]["start_page"], "end_page": group[-1]["end_page"],
                        "pages": group[-1]["end_page"] - group[0]["start_page"] + 1,
                    })
                return result

            final_chunks = []
            for ch in chapters_raw:
                secs = [s for s in sections_raw if ch["start_page"] <= s["start_page"] <= ch["end_page"]]
                for i, s in enumerate(secs):
                    s["end_page"] = secs[i+1]["start_page"] - 1 if i+1 < len(secs) else ch["end_page"]
                items = secs if secs else [
                    {"start_page": ch["start_page"], "end_page": ch["end_page"], "title": ch["title"]}
                ]
                final_chunks.extend(pack_by_budget(items, CHAR_BUDGET, f"제{ch['chapter']}장"))

            if appendix_items:
                final_chunks.extend(pack_by_budget(appendix_items, CHAR_BUDGET, "부록"))

            for chunk in final_chunks:
                chunk["start_page"] = chunk["start_page"] + offset
                chunk["end_page"] = min(chunk["end_page"] + offset, total_pages)

            return {"status": "success", "filename": file.filename, "total_pages": total_pages,
                    "total_chunks": len(final_chunks), "offset": offset, "chunks": final_chunks,
                    "note": "확인 후 /convert-by-chapters 에 chunks 그대로 전달하세요"}
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"목차 파싱 실패: {e}")


@app.post("/convert-by-chapters")
async def convert_by_chapters(file: UploadFile = File(...), chunks: str = Form("")):
    from pypdf import PdfReader, PdfWriter
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            reader = PdfReader(tmp_path)
            total_pages = len(reader.pages)
            if chunks:
                chunk_list = json.loads(chunks)
                ranges = [(ch["start_page"], ch["end_page"], ch.get("label", f"chunk{i}"))
                          for i, ch in enumerate(chunk_list)]
            else:
                ranges = [(i+1, min(i+100, total_pages), f"chunk{i//100+1}")
                          for i in range(0, total_pages, 100)]

            MAX_SPLIT_DEPTH = 6  # 이 이상 쪼개도 안 되면 포기(최소 단위 도달)

            async def convert_range_adaptive(start_page: int, end_page: int, label: str, depth: int = 0):
                """1-indexed 물리 페이지 범위. 실패해도 예외 던지지 않고 (markdown, failed_labels) 반환."""
                writer = PdfWriter()
                for pn in range(start_page - 1, end_page):
                    writer.add_page(reader.pages[pn])
                chunk_path = tmp_path + f"_chunk_{label}.pdf"
                with open(chunk_path, 'wb') as f:
                    writer.write(f)
                try:
                    with open(chunk_path, 'rb') as f:
                        chunk_content = f.read()
                    try:
                        md, finish_reason = await convert_pdf_to_markdown(chunk_content, f"{file.filename}_{label}")
                    except RuntimeError as e:
                        if "429" in str(e) or "quota" in str(e).lower():
                            print(f"🛑 QUOTA EXCEEDED — 중단: {label}: {e}")
                            raise
                        print(f"⚠️ ERROR converting {label}: {e}")
                        md, finish_reason = "", "ERROR"

                    if finish_reason == "STOP":
                        return md, []

                    pages = end_page - start_page + 1
                    if pages <= 1 or depth >= MAX_SPLIT_DEPTH:
                        print(f"⚠️ GIVE UP on {label} ({finish_reason}) at {pages}p, depth={depth}")
                        return md, [f"{label}({finish_reason})"]

                    mid = (start_page + end_page) // 2
                    left_md, left_failed = await convert_range_adaptive(start_page, mid, f"{label}-a", depth + 1)
                    right_md, right_failed = await convert_range_adaptive(mid + 1, end_page, f"{label}-b", depth + 1)
                    return left_md + "\n\n" + right_md, left_failed + right_failed
                finally:
                    if os.path.exists(chunk_path):
                        os.unlink(chunk_path)

            all_markdown = []
            all_failed = []
            for start, end, label in ranges:
                md, failed = await convert_range_adaptive(start, end, label)
                all_markdown.append(md)
                all_failed.extend(failed)

            combined = "\n\n".join(all_markdown)
            result = await process_pdf(content, file.filename, raw_markdown=combined)
            return {"status": "success", "filename": file.filename, "total_pages": total_pages,
                    "chunks_processed": len(ranges), "total_chars": len(combined),
                    "failed_segments": all_failed, **result}
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"챕터 분할 처리 실패: {e}")


# ── 검색 / Q&A ────────────────────────────────────────────────

@app.get("/stored-files")
async def stored_files_endpoint():
    try:
        files = get_stored_files()
        return {"stored_files": sorted(list(files)), "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/stored-files/{filename}")
async def delete_file_chunks(filename: str):
    from embeddings import delete_chunks_for_file
    try:
        delete_chunks_for_file(filename)
        return {"status": "deleted", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search")
async def search_documents(query: str, top_k: int = 5, task: str = "retrieval.query"):
    from embeddings import embed_texts, search
    try:
        vec = embed_texts([query], task=task)[0]
        hits = search(vec, top_k=top_k)
        results = [
            {"score": h.score, "content": h.payload["content"][:200] + "...",
             "source_file": h.payload["source_file"],
             "title": h.payload.get("title", ""),
             "chunk_index": h.payload.get("chunk_index")}
            for h in hits
        ]
        return {"query": query, "results": results}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat")
async def chat_endpoint(query: str = Form(...), top_k: int = Form(5)):
    try:
        return await pipeline_chat(query, top_k=top_k)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat 처리 중 오류: {e}")


@app.post("/classify-receipt")
async def classify_receipt_endpoint(file: UploadFile = File(...)):
    try:
        content = await file.read()
        result = await pipeline_classify_receipt(content, file.filename)
        return {"status": "success", **result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영수증 분류 중 오류: {e}")


@app.post("/review-settlement")
async def review_settlement_endpoint(
    files: list[UploadFile] = File(...),
    total_budget: int | None = Form(None),
):
    try:
        file_data = [(await f.read(), f.filename) for f in files]
        result = await pipeline_review_settlement(file_data, total_budget)
        return {"status": "success", **result}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"정산보고서 검토 중 오류: {e}")


# ── 탐지 / 디버그 ─────────────────────────────────────────────

@app.post("/detect-tier")
async def detect_tier_endpoint(file: UploadFile = File(...)):
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            tier, reason = detect_chunking_tier(tmp_path)
            preview = extract_first_pages_text(tmp_path, max_pages=20)
            toc_lines = re.findall(r'제\d+[장절]\s+[^\n]+[·\s·]+\s*\d+\s*$', preview, re.MULTILINE)[:5]
            return {"filename": file.filename, "tier": tier, "reason": reason,
                    "toc_lines_found": toc_lines,
                    "has_page_markers": bool(re.search(r'[/\\]\s*\d+\s*[/\\]', preview))}
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tier 탐지 실패: {e}")


@app.post("/test-gemini-parse")
async def test_gemini_parse(file: UploadFile = File(...)):
    try:
        content = await file.read()
        markdown, finish_reason = await convert_pdf_to_markdown(content, file.filename)
        return {"status": "success", "filename": file.filename, "finish_reason": finish_reason,
                "char_count": len(markdown), "result": markdown}
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/detect-noise-patterns")
async def detect_noise_patterns(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sample = content.decode('utf-8')[:30000]
        prompt = f"""다음 Markdown 문서에서 정제가 필요한 노이즈 패턴을 찾아주세요.

반환 형식 (JSON만 출력, 설명 없이):
{{"patterns": [{{"description": "이미지 참조", "example": "![](_page_0_Picture_3.jpeg)",
"regex": "!\\\\[\\\\]\\\\([^)]+\\\\.jpeg\\\\)", "action": "remove"}}]}}

분석 대상:
{sample}"""
        model = genai.GenerativeModel('gemini-3.1-flash-lite-preview')
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
        patterns_data = json.loads(text.strip())
        return {"status": "success", "filename": file.filename,
                "sample_size": len(sample), "patterns": patterns_data.get("patterns", [])}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Gemini 응답 파싱 실패: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"노이즈 패턴 감지 실패: {e}")
