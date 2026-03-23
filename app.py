"""
AI 사업비 집행 챗봇 - PDF 문서 처리 서버

주요 기능:
1. PDF → Markdown 변환 (Gemini 2.5 Flash-Lite, File API)
2. 노이즈 제거 및 청킹 (구조 기반)
3. GPU 임베딩 (워크스테이션 Jina v3)
4. Qdrant 벡터 저장
5. 의미론적 검색
6. 폴더 단위 배치 처리 (중복 스킵)

파이프라인:
PDF → Gemini File API → 노이즈 제거 → 청킹 → GPU 임베딩 → Qdrant 저장 → 검색

작성일: 2026-03-05
최종 수정: 2026-03-19 (File API 전환, 배치 처리 추가)
"""

from fastapi import FastAPI, File, UploadFile, HTTPException
import re
import requests
import os
import json
import tempfile
from pathlib import Path

# Qdrant 벡터 DB
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Gemini API
import google.generativeai as genai


app = FastAPI(title="PDF Document Processing Server")

# ==================== 설정 ====================
qdrant_client = QdrantClient(host="qdrant", port=6333)

EMBEDDING_SERVER = "http://100.88.194.30:5001"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_API_KEY_HERE")
genai.configure(api_key=GEMINI_API_KEY)

GEMINI_MODEL = genai.GenerativeModel(
    model_name='gemini-2.5-flash-lite',
    system_instruction="""
# Role
Expert in document data extraction and Markdown conversion.

# Rules
1. Convert ALL tables to markdown table format (|---|) without omission. For merged cells, split rows logically.
2. Preserve Korean and English text exactly as-is. Do NOT correct typos or rephrase.
3. Reflect document hierarchy using #, ## for headings and subheadings.
4. For images or complex diagrams, mark position only as [Image: description] or [Diagram: description].
5. Output pure Markdown ONLY. No preamble like "Here is the result" or "I understood".
"""
)
GEMINI_CONFIG = genai.types.GenerationConfig(temperature=0.0)

MAX_CHUNK_SIZE = 1500
COLLECTION_NAME = "documents"

# ==================== Qdrant 초기화 ====================
def init_qdrant_collection():
    try:
        collections = qdrant_client.get_collections().collections
        exists = any(col.name == COLLECTION_NAME for col in collections)

        if not exists:
            qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE)
            )
            print(f"✅ Collection '{COLLECTION_NAME}' created")
        else:
            print(f"✅ Collection '{COLLECTION_NAME}' already exists")
    except Exception as e:
        print(f"⚠️ Qdrant initialization error: {e}")

@app.on_event("startup")
async def startup_event():
    init_qdrant_collection()

# ==================== 유틸리티 함수 ====================

def get_stored_files() -> set:
    """Qdrant에 이미 저장된 파일명 목록 반환"""
    try:
        result = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            with_payload=True,
            limit=10000
        )
        files = set()
        for point in result[0]:
            source = point.payload.get("source_file", "")
            if source:
                files.add(source)
        return files
    except Exception:
        return set()


async def convert_pdf_with_gemini(file_content: bytes, filename: str) -> str:
    """
    Gemini File API로 PDF → Markdown 변환

    File API 사용 이유:
    - inline_data(base64)는 ~20MB 제한
    - File API는 2GB까지 지원, 크기 무관하게 동일 방식 처리

    프로세스:
    1. 임시 파일 저장
    2. Google File API에 업로드
    3. Gemini가 URI로 직접 읽어서 변환
    4. 업로드된 파일 즉시 삭제
    """
    file_size_mb = len(file_content) / (1024 * 1024)
    print(f"📤 Uploading {filename} ({file_size_mb:.1f}MB) to File API...")

    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    uploaded = None
    try:
        uploaded = genai.upload_file(tmp_path, mime_type="application/pdf")
        print(f"✅ File uploaded: {uploaded.uri}")

        response = GEMINI_MODEL.generate_content(
            [uploaded, "Convert this PDF to Markdown."],
            generation_config=GEMINI_CONFIG
        )

        markdown_text = response.text
        print(f"✅ Gemini conversion: {len(markdown_text):,} chars")
        return markdown_text

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini 변환 실패: {str(e)}")

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if uploaded:
            try:
                genai.delete_file(uploaded.name)
                print(f"🗑️ File deleted from File API")
            except Exception:
                pass


def clean_markdown(raw_content: str) -> str:
    """Markdown 노이즈 제거 (Gemini 결과물 기준)"""
    content = raw_content
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
    content = content.replace('\u0000', '')
    return content.strip()


def remove_table_of_contents(content: str) -> str:
    """목차 섹션 제거"""
    content = re.sub(
        r'^제\d+[장절]\s+[^·]+\s+[·]+\s+\d+\s*$', '', content, flags=re.MULTILINE
    )
    content = re.sub(
        r'^\d+\.\s+[^·]+\s+[·]+\s+\d+\s*$', '', content, flags=re.MULTILINE
    )
    content = re.sub(
        r'(CONTENTS|목\s*차|표\s*목차|그림\s*목차).*?(?=제\d+[장절]\s+\S)',
        '', content, flags=re.DOTALL
    )
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content


def extract_section_title(chunk: str) -> str:
    """섹션 제목 추출"""
    patterns = [
        r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*(.+)$',
        r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s+(.+)$',
        r'^제\d+[장절]\s+(.+)$',
        r'^\d+\.\s+(.+)$'
    ]
    for pattern in patterns:
        match = re.search(pattern, chunk, re.MULTILINE)
        if match:
            return match.group(1).strip()[:50]
    for line in chunk.split('\n'):
        line = line.strip()
        if len(line) > 10:
            return line[:50]
    return "untitled"


def split_long_paragraph(para: str, max_size: int) -> list[str]:
    return [para[i:i+max_size] for i in range(0, len(para), max_size)]


def chunk_by_heading(content: str, max_chunk_size: int = MAX_CHUNK_SIZE) -> list[str]:
    """한국어 문서 구조 기반 청킹"""
    sections = re.split(
        r'(?=^제\d+[장절]\s)|(?=^[①②③④⑤⑥⑦⑧⑨⑩]\s)|(?=^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s)',
        content, flags=re.MULTILINE
    )
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk_size:
            chunks.append(section)
            continue
        paragraphs = section.split('\n\n')
        current_chunk = ""
        for para in paragraphs:
            if len(para) > max_chunk_size:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                chunks.extend(split_long_paragraph(para, max_chunk_size))
                continue
            if len(current_chunk) + len(para) < max_chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
                current_chunk = para + "\n\n"
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
    return chunks


def is_vertical_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) == 1:
        return True
    if stripped in ['(', ')', '()', ')(']:
        return True
    if len(stripped) <= 3 and any(c.isdigit() for c in stripped):
        return True
    if len(stripped) <= 3 and all(c in '∙·○□■()' for c in stripped):
        return True
    return False


def clean_chunk_content(chunk: str) -> str:
    lines = chunk.split('\n')
    cleaned_lines = []
    vertical_buffer = []
    vertical_count = 0
    for line in lines:
        if is_vertical_table_line(line):
            vertical_count += 1
            vertical_buffer.append(line)
        else:
            if vertical_count < 3:
                cleaned_lines.extend(vertical_buffer)
            vertical_count = 0
            vertical_buffer = []
            cleaned_lines.append(line)
    if vertical_count < 3:
        cleaned_lines.extend(vertical_buffer)
    return '\n'.join(cleaned_lines)


def filter_appendix_chunks(chunks: list[str]) -> list[str]:
    """청크 필터링 + 내부 청소"""
    filtered = []
    for chunk in chunks:
        cleaned_chunk = clean_chunk_content(chunk)
        if len(cleaned_chunk.strip()) < 50:
            continue
        cleaned_no_space = cleaned_chunk.replace('\n', '').replace(' ', '')
        if len(cleaned_no_space) > 0:
            paren_count = cleaned_no_space.count('(') + cleaned_no_space.count(')')
            paren_ratio = paren_count / len(cleaned_no_space)
            symbol_count = sum(cleaned_no_space.count(c) for c in '∙·○□■')
            symbol_ratio = symbol_count / len(cleaned_no_space)
            if (paren_ratio + symbol_ratio) > 0.5:
                continue
        lines = cleaned_chunk.split('\n')
        single_char_lines = sum(1 for line in lines if len(line.strip()) <= 2 and line.strip())
        if single_char_lines > len(lines) * 0.8:
            continue
        filtered.append(cleaned_chunk)
    return filtered


async def process_pdf(file_content: bytes, filename: str) -> dict:
    """
    단일 PDF 처리 파이프라인 (내부 공통 함수)

    1. Gemini File API 변환
    2. 노이즈 제거
    3. 목차 제거
    4. 청킹
    5. 청크 필터링
    6. GPU 임베딩
    7. Qdrant 저장 (기존 동일 파일 청크 교체)
    """
    # 1. Gemini 변환
    print(f"Step 1/6: Converting {filename} with Gemini File API...")
    raw_markdown = await convert_pdf_with_gemini(file_content, filename)

    # 변환 결과 markdown 파일로 저장 (품질 확인용)
    output_path = Path("/app/manual/output") / (Path(filename).stem + ".md")
    try:
        output_path.write_text(raw_markdown, encoding="utf-8")
        print(f"💾 Markdown saved: {output_path}")
    except Exception as e:
        print(f"⚠️ Markdown save failed: {e}")

    # 2. 노이즈 제거
    print("Step 2/6: Cleaning markdown...")
    clean_content = clean_markdown(raw_markdown)

    # 3. 목차 제거
    print("Step 3/6: Removing table of contents...")
    content_without_toc = remove_table_of_contents(clean_content)

    # 4. 청킹
    print("Step 4/6: Chunking...")
    chunks = chunk_by_heading(content_without_toc, max_chunk_size=1500)

    # 5. 청크 필터링
    print("Step 5/6: Filtering chunks...")
    filtered_chunks = filter_appendix_chunks(chunks)

    # 6. GPU 임베딩
    print(f"Step 6/6: Embedding {len(filtered_chunks)} chunks on GPU...")
    response = requests.post(
        f"{EMBEDDING_SERVER}/embed",
        json={"texts": filtered_chunks},
        timeout=600
    )
    embeddings_data = response.json()
    embeddings = embeddings_data["embeddings"]

    # 7. Qdrant 저장 (기존 동일 파일 청크 삭제 후 재저장)
    try:
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector={"filter": {"must": [{"key": "source_file", "match": {"value": filename}}]}}
        )
    except Exception:
        pass

    existing = qdrant_client.scroll(collection_name=COLLECTION_NAME, limit=10000, with_payload=False)
    max_id = max((p.id for p in existing[0]), default=-1)

    points = [
        PointStruct(
            id=max_id + 1 + idx,
            vector=embedding,
            payload={
                "content": chunk,
                "source_file": filename,
                "chunk_index": idx,
                "title": extract_section_title(chunk),
                "char_count": len(chunk)
            }
        )
        for idx, (chunk, embedding) in enumerate(zip(filtered_chunks, embeddings))
    ]
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"✅ Stored {len(points)} vectors for {filename}")

    return {
        "filename": filename,
        "chunks_count": len(filtered_chunks),
        "embeddings_count": len(embeddings),
        "vectors_stored": len(points),
        "gpu_device": embeddings_data["device"]
    }


# ==================== API 엔드포인트 ====================

@app.post("/convert-embed-store")
async def convert_embed_store(file: UploadFile = File(...)):
    """
    단일 PDF 처리
    PDF → Gemini File API → 노이즈 제거 → 청킹 → GPU 임베딩 → Qdrant
    """
    try:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다")

        content = await file.read()
        result = await process_pdf(content, file.filename)
        return {"status": "success", **result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파이프라인 처리 중 오류: {str(e)}")


@app.post("/convert-embed-store-batch")
async def convert_embed_store_batch(folder_path: str):
    """
    폴더 단위 배치 처리

    - 폴더 내 PDF 전체 스캔
    - 이미 Qdrant에 저장된 파일은 스킵 (중복 방지, API 사용량 절약)
    - 신규/변경 파일만 처리

    Args:
        folder_path: PDF 폴더 경로 (컨테이너 내부 경로)
    """
    try:
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            raise HTTPException(status_code=400, detail=f"폴더를 찾을 수 없습니다: {folder_path}")

        pdf_files = list(folder.glob("*.pdf"))
        if not pdf_files:
            raise HTTPException(status_code=400, detail="폴더에 PDF 파일이 없습니다")

        stored_files = get_stored_files()
        print(f"📂 Found {len(pdf_files)} PDFs, {len(stored_files)} already stored")

        processed = []
        skipped = []
        failed = []

        for pdf_path in sorted(pdf_files):
            filename = pdf_path.name

            if filename in stored_files:
                print(f"⏭️ Skipping {filename} (already stored)")
                skipped.append(filename)
                continue

            try:
                print(f"\n{'='*50}")
                print(f"📄 Processing: {filename}")
                content = pdf_path.read_bytes()
                result = await process_pdf(content, filename)
                processed.append(result)
            except Exception as e:
                print(f"❌ Failed: {filename} - {str(e)}")
                failed.append({"filename": filename, "error": str(e)})

        return {
            "status": "success",
            "total_files": len(pdf_files),
            "processed": processed,
            "skipped": skipped,
            "failed": failed
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"배치 처리 중 오류: {str(e)}")


@app.get("/stored-files")
async def stored_files_endpoint():
    """Qdrant에 저장된 파일 목록 조회"""
    try:
        files = get_stored_files()
        return {"stored_files": sorted(list(files)), "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 목록 조회 오류: {str(e)}")


@app.get("/search")
async def search_documents(query: str, top_k: int = 5):
    """의미론적 검색 (Semantic Search)"""
    try:
        response = requests.post(
            f"{EMBEDDING_SERVER}/embed",
            json={"texts": [query]},
            timeout=60
        )
        query_vector = response.json()["embeddings"][0]

        search_results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k
        )

        results = [
            {
                "score": hit.score,
                "content": hit.payload["content"][:200] + "...",
                "source_file": hit.payload["source_file"],
                "title": hit.payload["title"],
                "chunk_index": hit.payload["chunk_index"]
            }
            for hit in search_results
        ]

        return {"query": query, "results": results}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 중 오류: {str(e)}")


@app.post("/detect-noise-patterns")
async def detect_noise_patterns(file: UploadFile = File(...)):
    """Gemini로 Markdown 노이즈 패턴 자동 감지"""
    try:
        content = await file.read()
        markdown = content.decode('utf-8')
        sample = markdown[:30000]

        prompt = f"""
다음 Markdown 문서에서 정제가 필요한 노이즈 패턴을 찾아주세요.

반환 형식 (JSON만 출력, 설명 없이):
{{
  "patterns": [
    {{
      "description": "이미지 참조",
      "example": "![](_page_0_Picture_3.jpeg)",
      "regex": "!\\\\[\\\\]\\\\([^)]+\\\\.jpeg\\\\)",
      "action": "remove"
    }}
  ]
}}

분석 대상:
{sample}
"""
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        response = model.generate_content(prompt)

        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:]
        if response_text.endswith('```'):
            response_text = response_text[:-3]

        patterns_data = json.loads(response_text.strip())

        return {
            "status": "success",
            "filename": file.filename,
            "sample_size": len(sample),
            "patterns": patterns_data.get("patterns", [])
        }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Gemini 응답 파싱 실패: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"노이즈 패턴 감지 실패: {str(e)}")


@app.post("/test-gemini-parse")
async def test_gemini_parse(file: UploadFile = File(...)):
    """Gemini PDF 직접 파싱 테스트 (저장 없음, 품질 확인용)"""
    try:
        content = await file.read()
        markdown = await convert_pdf_with_gemini(content, file.filename)
        return {
            "status": "success",
            "filename": file.filename,
            "char_count": len(markdown),
            "result": markdown
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini 파싱 실패: {str(e)}")


@app.get("/")
def root():
    return {"message": "PDF to Markdown API", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy"}