import os
import re
import tempfile

MAX_CHUNK_SIZE = 1500
MIN_CHUNK_SIZE = 300


# ── 노이즈 제거 ──────────────────────────────────────────────

def clean_markdown(raw_content: str) -> str:
    content = re.sub(r'\n{3,}', '\n\n', raw_content)
    content = re.sub(r'[ \t]+$', '', content, flags=re.MULTILINE)
    content = content.replace('　', '')
    content = re.sub(r'(?<=[가-힣a-zA-Z0-9])\n(?=[가-힣a-zA-Z0-9])', ' ', content)
    return content.strip()


def remove_table_of_contents(content: str) -> str:
    content = re.sub(r'^제\d+[장절]\s+[^·]+\s+[·]+\s+\d+\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'^\d+\.\s+[^·]+\s+[·]+\s+\d+\s*$', '', content, flags=re.MULTILINE)
    content = re.sub(
        r'(CONTENTS|목\s*차|표\s*목차|그림\s*목차).*?(?=제\d+[장절]\s+\S)',
        '', content, flags=re.DOTALL,
    )
    return re.sub(r'\n{3,}', '\n\n', content)


# ── 공통 유틸 ────────────────────────────────────────────────

def extract_section_title(chunk: str) -> str:
    patterns = [
        r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*(.+)$',
        r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s+(.+)$',
        r'^제\d+[장절]\s+(.+)$',
        r'^\d+\.\s+(.+)$',
    ]
    for pattern in patterns:
        m = re.search(pattern, chunk, re.MULTILINE)
        if m:
            return m.group(1).strip()[:50]
    for line in chunk.split('\n'):
        line = line.strip()
        if len(line) > 10:
            return line[:50]
    return "untitled"


def _split_long_paragraph(para: str, max_size: int) -> list[str]:
    return [para[i:i + max_size] for i in range(0, len(para), max_size)]


def _is_vertical_table_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if len(s) == 1:
        return True
    if s in ['(', ')', '()', ')(']:
        return True
    if len(s) <= 3 and any(c.isdigit() for c in s):
        return True
    if len(s) <= 3 and all(c in '∙·○□■()' for c in s):
        return True
    return False


def _clean_chunk_content(chunk: str) -> str:
    lines = chunk.split('\n')
    cleaned, buf, count = [], [], 0
    for line in lines:
        if _is_vertical_table_line(line):
            count += 1
            buf.append(line)
        else:
            if count < 3:
                cleaned.extend(buf)
            count, buf = 0, []
            cleaned.append(line)
    if count < 3:
        cleaned.extend(buf)
    return '\n'.join(cleaned)


def filter_chunks(chunks: list[str]) -> list[str]:
    filtered = []
    for chunk in chunks:
        c = _clean_chunk_content(chunk)
        if len(c.strip()) < 50:
            continue
        ns = c.replace('\n', '').replace(' ', '')
        if ns:
            pr = (ns.count('(') + ns.count(')')) / len(ns)
            sr = sum(ns.count(x) for x in '∙·○□■') / len(ns)
            if pr + sr > 0.5:
                continue
        lines = c.split('\n')
        if sum(1 for l in lines if len(l.strip()) <= 2 and l.strip()) > len(lines) * 0.8:
            continue
        filtered.append(c)
    return filtered


# ── Tier 3: 글자수 기반 (fallback) ──────────────────────────

def chunk_by_size(content: str, max_chunk_size: int = MAX_CHUNK_SIZE) -> list[str]:
    sections = re.split(
        r'(?=^제\d+[장절]\s)|(?=^[①②③④⑤⑥⑦⑧⑨⑩]\s)|(?=^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\s)',
        content, flags=re.MULTILINE,
    )
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk_size:
            chunks.append(section)
            continue
        cur = ""
        for para in section.split('\n\n'):
            if len(para) > max_chunk_size:
                if cur.strip():
                    chunks.append(cur.strip())
                    cur = ""
                chunks.extend(_split_long_paragraph(para, max_chunk_size))
                continue
            if len(cur) + len(para) < max_chunk_size:
                cur += para + "\n\n"
            else:
                if cur.strip():
                    chunks.append(cur.strip())
                cur = para + "\n\n"
        if cur.strip():
            chunks.append(cur.strip())
    return chunks


# ── Tier 2: Heading 기반 (breadcrumb) ───────────────────────

def chunk_by_markdown_heading(
    content: str,
    min_chunk_size: int = MIN_CHUNK_SIZE,
    max_chunk_size: int = MAX_CHUNK_SIZE,
) -> list[str]:
    heading_re = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    boundaries = [
        (m.start(), len(m.group(1)), m.group(2).strip())
        for m in heading_re.finditer(content)
    ]

    if not boundaries:
        return [content[i:i + max_chunk_size] for i in range(0, len(content), max_chunk_size)]

    sections = []
    for idx, (start, level, title) in enumerate(boundaries):
        end = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(content)
        raw = content[start:end]
        body = raw[raw.index('\n'):].strip() if '\n' in raw else ''
        sections.append((level, title, body))

    stack: list[str] = []
    raw_chunks = []
    for level, title, body in sections:
        stack = stack[:level - 1]
        stack.append(title)
        breadcrumb = ' > '.join(stack[:-1]) if len(stack) > 1 else ''
        prefix = f"[{breadcrumb}] {title}\n" if breadcrumb else f"{title}\n"
        raw_chunks.append(prefix + body)

    # size-pack
    packed: list[str] = []
    buffer = ""
    for chunk in raw_chunks:
        if not buffer:
            buffer = chunk
            continue
        if len(buffer) < min_chunk_size or len(buffer) + len(chunk) <= max_chunk_size:
            buffer += "\n\n" + chunk
        else:
            packed.append(buffer)
            buffer = chunk
    if buffer:
        packed.append(buffer)

    # 초과 chunk 재분할
    final: list[str] = []
    for chunk in packed:
        if len(chunk) <= max_chunk_size:
            final.append(chunk)
            continue
        sub = ""
        for part in chunk.split('\n\n'):
            if len(sub) + len(part) + 2 <= max_chunk_size:
                sub = (sub + "\n\n" + part).lstrip()
            else:
                if sub:
                    final.append(sub)
                final.extend(part[i:i + max_chunk_size] for i in range(0, len(part), max_chunk_size))
                sub = ""
        if sub:
            final.append(sub)

    return [c for c in final if c.strip()]


# ── Tier 탐지 ────────────────────────────────────────────────

def extract_first_pages_text(pdf_path: str, max_pages: int = 20) -> str:
    from markitdown import MarkItDown
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for i in range(min(max_pages, len(reader.pages))):
        writer.add_page(reader.pages[i])

    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
        writer.write(tmp)
        slice_path = tmp.name
    try:
        return MarkItDown().convert(slice_path).text_content
    finally:
        if os.path.exists(slice_path):
            os.unlink(slice_path)


def detect_toc(text: str) -> bool:
    has_chapters = bool(re.search(r'제\d+[장절]\s+[^\n]+[·\s·]+\s*\d+\s*$', text, re.MULTILINE))
    has_markers = bool(re.search(r'[/\\]\s*\d+\s*[/\\]', text))
    return has_chapters and has_markers


def detect_heading_structure(markdown: str) -> bool:
    return bool(re.search(r'^#{1,6}\s', markdown, re.MULTILINE))


def detect_chunking_tier(pdf_path: str) -> tuple[int, str]:
    try:
        text = extract_first_pages_text(pdf_path, max_pages=20)
        if detect_toc(text):
            return 1, "TOC detected (chapter pattern + page markers)"
        return 2, "No TOC — will check heading structure after Gemini conversion"
    except Exception as e:
        return 2, f"TOC detection failed ({e}) — fallback to heading-based"


def select_and_chunk(markdown: str) -> tuple[list[str], str]:
    if detect_heading_structure(markdown):
        return chunk_by_markdown_heading(markdown), "tier2-heading"
    return chunk_by_size(markdown), "tier3-size"
