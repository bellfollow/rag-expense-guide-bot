"""분산이 어느 단계에서 시작하는지 국소화한다.

같은 이미지를 N번 태워서 단계별 출력을 그대로 비교한다.
정확도가 아니라 **동일성**을 본다 — 값이 실행마다 바뀌는지.

사용:
  python variance_probe.py --api http://localhost:5000 --files 20260803_133500.jpg 20260808_202931.jpg
  python variance_probe.py --api http://localhost:5000 --labels labels_prefilled_1.csv --ids r001 r002 r004
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


# 단계별로 뽑아볼 필드. (라벨, 경로) — 순서가 파이프라인 순서다.
FIELDS = [
    ("① 추출", "extracted", "vendor"),
    ("① 추출", "extracted", "item"),
    ("① 추출", "extracted", "amount"),
    ("① 추출", "extracted", "date"),
    ("② 분류", "classification", "main_category"),
    ("② 분류", "classification", "sub_item"),
    ("② 분류", "classification", "flag"),
    ("② 분류", "classification", "confidence"),
    ("④ 컴플라이언스", "compliance", "compliance_status"),
    ("④ 컴플라이언스", "compliance", "citation"),
    ("④ 컴플라이언스", "compliance", "override_flag"),
]


def probe(api, path, n):
    runs = []
    for i in range(n):
        with path.open("rb") as f:
            r = requests.post(f"{api}/classify-receipt", files={"file": (path.name, f)}, timeout=180)
        if r.status_code != 200:
            print(f"  run{i+1} 실패: HTTP {r.status_code} {r.text[:120]}")
            continue
        d = r.json()
        rec = {f"{label}.{key}": d.get(sec, {}).get(key) for label, sec, key in FIELDS}
        # ③ 검색은 어떤 문서가 올라왔는지로 본다
        rec["③ 검색.sources"] = "|".join(s["source_file"] for s in d.get("sources", []))
        rec["③ 검색.top_score"] = (d.get("sources") or [{}])[0].get("score")
        runs.append(rec)
        print(f"  run{i+1} ok", flush=True)
    return runs


def report(name, runs, out_lines):
    if len(runs) < 2:
        out_lines.append(f"\n## {name} — 실행 {len(runs)}회, 비교 불가\n")
        return
    out_lines.append(f"\n## {name} ({len(runs)}회)\n")
    out_lines.append("| 단계 | 필드 | 고유값 | 값 |")
    out_lines.append("|---|---|---|---|")

    # FIELDS 선언 순서가 곧 파이프라인 순서다. 정렬하지 마라 —
    # 알파벳 정렬하면 classification이 extracted보다 앞에 와서 최초 지점을 잘못 찍는다.
    keys = [f"{label}.{key}" for label, _, key in FIELDS[:4]]          # ① 추출
    keys += [f"{label}.{key}" for label, _, key in FIELDS[4:8]]        # ② 분류
    keys += ["③ 검색.sources", "③ 검색.top_score"]                     # ③ 검색
    keys += [f"{label}.{key}" for label, _, key in FIELDS[8:]]         # ④ 컴플라이언스
    first_unstable = None
    for k in keys:
        vals = [r.get(k) for r in runs]
        uniq = Counter(str(v) for v in vals)
        stage, field = k.split(".", 1)
        if len(uniq) == 1:
            shown = str(vals[0])
            shown = shown[:60] + ("…" if len(shown) > 60 else "")
            out_lines.append(f"| {stage} | `{field}` | 1 ✅ | {shown} |")
        else:
            if first_unstable is None:
                first_unstable = (stage, field)
            shown = " / ".join(
                (s[:40] + "…" if len(s) > 40 else s) for s in list(uniq)[:3]
            )
            out_lines.append(f"| {stage} | `{field}` | **{len(uniq)} 🚨** | {shown} |")

    if first_unstable:
        out_lines.append(f"\n**최초 불안정 지점: {first_unstable[0]} / `{first_unstable[1]}`**")
        if first_unstable[0].startswith("①"):
            out_lines.append("→ 추출(vision)부터 흔들린다. 하류는 결정론적이어도 결과가 갈린다. "
                             "추출 프롬프트에 표기 규칙을 못박는 것이 먼저다.")
        elif first_unstable[0].startswith("②"):
            out_lines.append("→ 추출은 결백. 분류가 같은 입력에 다른 답을 낸다. "
                             "판단 근거가 부족해서 비슷한 확률의 후보 사이에서 흔들리는 것 — "
                             "분류 단계에 근거(RAG 또는 taxonomy 보강)를 줘야 한다.")
        elif first_unstable[0].startswith("③"):
            out_lines.append("→ 분류까지 동일한데 검색 결과가 다르다. Qdrant/임베딩 쪽을 봐야 한다.")
        else:
            out_lines.append("→ 검색 결과까지 동일한데 컴플라이언스가 다른 결론을 낸다. "
                             "이 단계 프롬프트가 흔들리는 것.")
    else:
        out_lines.append("\n**전 단계 완전히 동일 — 이 영수증은 흔들리지 않는다.**")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:5000")
    p.add_argument("--images", type=Path, default=Path("."))
    p.add_argument("--files", nargs="*", default=[], help="파일명 직접 지정")
    p.add_argument("--labels", type=Path, help="labels csv (--ids와 함께)")
    p.add_argument("--ids", nargs="*", default=[], help="라벨 id로 지정 (예: r001 r002 r004)")
    p.add_argument("-n", type=int, default=3, help="반복 횟수 (기본 3)")
    p.add_argument("--report", type=Path, default=Path("variance_probe.md"))
    a = p.parse_args()

    targets = list(a.files)
    if a.ids:
        if not a.labels:
            raise SystemExit("--ids를 쓰려면 --labels도 필요하다")
        import pandas as pd
        df = pd.read_csv(a.labels, dtype=str)
        targets += df[df["id"].isin(a.ids)]["file"].tolist()
    if not targets:
        raise SystemExit("--files 또는 --labels+--ids 중 하나는 필요하다")

    index = build_index(a.images)
    missing = [f for f in targets if f not in index]
    if missing:
        raise SystemExit(f"이미지 못 찾음: {missing}")

    print(f"대상 {len(targets)}장 × {a.n}회 = {len(targets)*a.n}콜\n")
    lines = [f"# 분산 국소화 ({len(targets)}장 × {a.n}회)\n",
             "정확도가 아니라 **동일성**을 본다. 값이 실행마다 바뀌면 🚨.\n"]
    for f in targets:
        print(f"[{f}]")
        report(f, probe(a.api, index[f], a.n), lines)

    a.report.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines))
