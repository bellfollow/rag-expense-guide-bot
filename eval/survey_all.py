"""전체 사진을 파이프라인에 태워 분포만 본다 — 평가셋 확장 여지가 있는지 판정용.

⚠ 여기 나온 판정을 정답으로 쓰지 마라. 후보 선별용이다.
   모델 출력을 라벨로 쓰면 시스템이 자기 답을 채점하는 순환이 된다.

사용:
  python survey_all.py --api http://localhost:5000 --exclude labels_prefilled_1.csv
"""
import argparse, json
from collections import Counter
from pathlib import Path
import requests


SKIP_DIRS = {".venv", "venv", "site-packages", "__pycache__", "node_modules", ".git"}


def build_index(images: Path) -> dict:
    """하위 폴더 재귀. 라이브러리 샘플 이미지(skimage 등)를 긁지 않도록 가상환경은 제외한다."""
    idx, dup = {}, []
    for p in sorted(images.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        if p.name in idx:
            dup.append(p.name)
        else:
            idx[p.name] = p
    if dup:
        print(f"[경고] 파일명 중복 {len(set(dup))}개 — 먼저 찾은 것 사용: {sorted(set(dup))[:5]}")
    return idx


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:5000")
    p.add_argument("--images", type=Path, default=Path("."))
    p.add_argument("--exclude", type=Path, default=Path(__file__).parent / "labels_prefilled.csv", help="이미 평가셋에 든 파일 목록 csv (file 컬럼)")
    p.add_argument("--out", type=Path, default=Path("survey.jsonl"))
    p.add_argument("--report", type=Path, default=Path("survey.md"))
    a = p.parse_args()

    index = build_index(a.images)
    already = set()
    if a.exclude and a.exclude.exists():
        import pandas as pd
        already = set(pd.read_csv(a.exclude, dtype=str)["file"])

    targets = [n for n in index if n not in already]
    done = set()
    if a.out.exists():
        done = {json.loads(l)["file"] for l in a.out.read_text(encoding="utf-8").splitlines()
                if l.strip() and "error" not in json.loads(l)}
    todo = [n for n in targets if n not in done]

    print(f"전체 {len(index)}장 / 평가셋 제외 {len(targets)}장 / 남은 {len(todo)}장\n")

    for i, name in enumerate(todo, 1):
        rec = {"file": name}
        try:
            with index[name].open("rb") as f:
                r = requests.post(f"{a.api}/classify-receipt",
                                  files={"file": (name, f)}, timeout=180)
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}"
            else:
                d = r.json()
                rec.update({
                    "vendor": d["extracted"].get("vendor"),
                    "item": d["extracted"].get("item"),
                    "amount": d["extracted"].get("amount"),
                    "date": d["extracted"].get("date"),
                    "sub_item": d["classification"].get("sub_item"),
                    "flag": d["classification"].get("flag"),
                    "confidence": d["classification"].get("confidence"),
                    "reasoning": d["classification"].get("reasoning"),
                })
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        with a.out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {name} {rec.get('flag') or rec.get('error')}", flush=True)

    # ── 리포트 ──
    rows = [json.loads(l) for l in a.out.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "error" not in r]
    L = [f"# 미검토 사진 조사 ({len(ok)}장)\n",
         "⚠ 모델 판정은 **후보 선별용**이다. 정답으로 쓰지 마라.\n",
         "## flag 분포\n"]
    for k, v in Counter(r.get("flag") for r in ok).most_common():
        L.append(f"- `{k}`: {v}건")

    L.append("\n## sub_item 분포\n")
    for k, v in Counter(r.get("sub_item") for r in ok).most_common():
        L.append(f"- `{k}`: {v}건")

    hard = [r for r in ok if r.get("flag") == "지원불가"]
    L.append(f"\n## 지원불가 후보 {len(hard)}건 — 평가셋 확장 1순위\n")
    L.append("| 파일 | 상호 | 품목 | 금액 |\n|---|---|---|---|")
    for r in hard:
        L.append(f"| `{r['file']}` | {r.get('vendor')} | {r.get('item')} | {r.get('amount')} |")

    normal = [r for r in ok if r.get("flag") == "정상"]
    L.append(f"\n## 정상 후보 {len(normal)}건 — 현재 평가셋에 0건인 클래스\n")
    L.append("| 파일 | 상호 | 품목 | 비목 |\n|---|---|---|---|")
    for r in normal:
        L.append(f"| `{r['file']}` | {r.get('vendor')} | {r.get('item')} | {r.get('sub_item')} |")

    # 새 비목이 등장했는지 — 기존 평가셋엔 해당없음/국내여비뿐이었다
    seen = {"해당없음", "국내여비(운임/숙박비/식비/일비)", "국내여비(식비)", None}
    novel = [r for r in ok if r.get("sub_item") not in seen]
    L.append(f"\n## 새 비목이 붙은 건 {len(novel)}건 — 클래스 다양성 확보 후보\n")
    L.append("| 파일 | 비목 | 상호 | 품목 |\n|---|---|---|---|")
    for r in novel:
        L.append(f"| `{r['file']}` | **{r.get('sub_item')}** | {r.get('vendor')} | {r.get('item')} |")

    err = [r for r in rows if "error" in r]
    if err:
        L.append(f"\n## 처리 실패 {len(err)}건\n")
        for r in err[:10]:
            L.append(f"- `{r['file']}` {r['error']}")

    a.report.write_text("\n".join(L), encoding="utf-8")
    print("\n" + "\n".join(L))
