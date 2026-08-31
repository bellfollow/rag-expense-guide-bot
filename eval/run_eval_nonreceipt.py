"""비영수증 거절(is_receipt) 채점 — 정답 확정된 negative set 전용.

run_eval.py는 --images 인덱싱 시 .venv/site-packages를 일부러 제외한다
(라이브러리 샘플 이미지가 섞이지 않도록). 여기서는 반대로 그 샘플 이미지들이
평가 대상이므로 필터링 없이 인덱싱한다.

사용:
  python run_eval_nonreceipt.py --api http://localhost:5000 --images <.venv가 있는 폴더>
"""
import argparse, json
from pathlib import Path
import pandas as pd
import requests


def build_index(images: Path) -> dict:
    idx, dup = {}, []
    for p in sorted(images.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if p.name in idx:
            dup.append(p.name)
        else:
            idx[p.name] = p
    if dup:
        print(f"[경고] 파일명 중복 {len(set(dup))}개 — 먼저 찾은 것 사용: {sorted(set(dup))[:5]}")
    return idx


def run(api, index, labels, out):
    df = pd.read_csv(labels, dtype=str).fillna("")
    done, keep = set(), []
    if out.exists():
        for l in out.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            d = json.loads(l)
            if "error" in d:
                continue
            done.add(d["id"])
            keep.append(l)
        out.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")

    for _, row in df.iterrows():
        if row["id"] in done:
            continue
        img = index[row["file"]]
        rec = {"id": row["id"], "file": row["file"]}
        try:
            with img.open("rb") as f:
                r = requests.post(f"{api}/classify-receipt", files={"file": (row["file"], f)}, timeout=180)
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            else:
                d = r.json()
                rec["got_is_receipt"] = d["extracted"].get("is_receipt")
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        rec["want_is_receipt"] = row["expected_is_receipt"].strip().lower() == "true"
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{row['id']:5s} {'ERR ' + rec['error'][:60] if 'error' in rec else 'ok'}", flush=True)


def score(out, report):
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "error" not in r]
    n = len(ok)
    if not n:
        print("성공 0건 — 전부 실패"); return
    hit = sum(1 for r in ok if r["got_is_receipt"] is False)
    L = [f"# 비영수증 거절 평가 ({n}/{len(rows)}건 성공)\n",
         f"**recall = {hit}/{n} ({hit/n*100:.0f}%)** — 전부 is_receipt=false가 정답인 negative set\n"]
    miss = [r for r in ok if r["got_is_receipt"] is not False]
    if miss:
        L.append("## 놓친 건 (is_receipt가 false로 안 나옴)\n")
        for r in miss:
            L.append(f"- `{r['id']}` {r['file']} → got_is_receipt={r['got_is_receipt']!r}")
    err = [r for r in rows if "error" in r]
    if err:
        L.append(f"\n## 처리 실패 {len(err)}건\n")
        for r in err:
            L.append(f"- `{r['id']}` {r['error'][:120]}")
    report.write_text("\n".join(L), encoding="utf-8")
    print("\n" + "\n".join(L))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:5000")
    p.add_argument("--labels", type=Path, default=Path(__file__).parent / "labels_nonreceipt.csv")
    p.add_argument("--images", type=Path, required=True, help=".venv가 들어있는 상위 폴더")
    p.add_argument("--out", type=Path, default=Path("eval_nonreceipt_result.jsonl"))
    p.add_argument("--report", type=Path, default=Path("eval_nonreceipt_report.md"))
    a = p.parse_args()

    try:
        requests.get(a.api, timeout=5)
    except Exception as e:
        raise SystemExit(f"앱에 연결 안 됨: {a.api}\n  {e}\n  앱이 떠 있는지 / 포트가 맞는지 확인.")

    index = build_index(a.images)
    print(f"이미지 {len(index)}개 인덱싱 ({a.images.resolve()} 하위 전체)")

    df = pd.read_csv(a.labels, dtype=str)
    miss = [f for f in df["file"] if f not in index]
    if miss:
        raise SystemExit(f"이미지 {len(miss)}개 못 찾음. 첫 5개: {miss[:5]}\n"
                         f"  --images 를 .venv가 들어있는 상위 폴더로 지정하라.")

    run(a.api, index, a.labels, a.out)
    score(a.out, a.report)
