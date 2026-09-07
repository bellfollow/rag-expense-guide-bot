"""
변환 품질 검증 스크립트
pypdf로 원문 텍스트 추출 → markdown과 키워드 카운트 비교
사용: python3 validate_conversion.py <pdf경로> [키워드1 키워드2 ...]
예:  python3 validate_conversion.py manual/guiideline.pdf 시제품 창업 집행 승인
"""
import sys
import re
from pathlib import Path


def extract_pdf_text(pdf_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def count_keyword(text: str, keyword: str) -> int:
    return len(re.findall(re.escape(keyword), text))


def top_words(text: str, n: int = 20) -> list[tuple[str, int]]:
    """한글 2자 이상 단어 빈도 상위 N개 (stopword 제외)"""
    STOPWORDS = {"있다", "하는", "하여", "경우", "대한", "위한", "관련", "따라", "기관",
                 "연구", "개발", "사업", "해당", "사항", "관리", "수행", "내용", "이상",
                 "이하", "또는", "으로", "에서", "에는", "하고", "하며", "으며", "있으며",
                 "있는", "하는", "것을", "것이", "것에", "것으로", "있어", "없는", "없이"}
    words = re.findall(r'[가-힣]{2,6}', text)
    freq: dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    return sorted(freq.items(), key=lambda x: -x[1])[:n]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 validate_conversion.py <pdf_path> [keyword ...]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    stem = Path(pdf_path).stem
    md_path = Path(f"manual/output/{stem}.md")

    if not Path(pdf_path).exists():
        print(f"PDF 없음: {pdf_path}"); sys.exit(1)
    if not md_path.exists():
        print(f"Markdown 없음: {md_path}"); sys.exit(1)

    print(f"PDF:      {pdf_path}")
    print(f"Markdown: {md_path}")
    print("=" * 60)

    pdf_text = extract_pdf_text(pdf_path)
    md_text  = md_path.read_text(encoding="utf-8")

    print(f"PDF 원문 글자수:    {len(pdf_text):,}")
    print(f"Markdown 글자수:    {len(md_text):,}")
    print(f"글자수 비율:        {len(md_text)/len(pdf_text)*100:.1f}%")
    print()

    # 사용자 지정 키워드
    keywords = sys.argv[2:] if len(sys.argv) > 2 else []

    # 키워드 미지정 시 PDF 빈도 상위 단어 자동 선정
    if not keywords:
        print("키워드 미지정 → PDF 빈도 상위 20개 자동 선정")
        keywords = [w for w, _ in top_words(pdf_text, 20)]

    print(f"{'키워드':<12} {'PDF':>6} {'Markdown':>10} {'비율':>8} {'상태':>6}")
    print("-" * 50)

    WARN_THRESHOLD = 0.7
    problems = []

    for kw in keywords:
        pdf_cnt = count_keyword(pdf_text, kw)
        md_cnt  = count_keyword(md_text, kw)
        ratio   = md_cnt / pdf_cnt if pdf_cnt > 0 else None
        status  = ""
        if pdf_cnt == 0:
            status = "N/A"
        elif ratio >= WARN_THRESHOLD:
            status = "✅"
        else:
            status = "⚠️"
            problems.append((kw, pdf_cnt, md_cnt, ratio))

        ratio_str = f"{ratio*100:.0f}%" if ratio is not None else "-"
        print(f"{kw:<12} {pdf_cnt:>6} {md_cnt:>10} {ratio_str:>8} {status:>6}")

    print()
    if problems:
        print(f"⚠️  누락 의심 키워드 ({len(problems)}개, 비율 < {WARN_THRESHOLD*100:.0f}%):")
        for kw, pc, mc, r in problems:
            print(f"  {kw}: PDF {pc}회 → MD {mc}회 ({r*100:.0f}%)")
    else:
        print("✅ 모든 키워드 변환율 양호")


if __name__ == "__main__":
    main()
