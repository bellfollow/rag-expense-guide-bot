"""/chat retrieval 채점 — Gemini 호출 없이 /search만 태운다.

정답은 답변 텍스트가 아니라 "정답 청크가 검색 top_k 안에 오는가"(hit@k, MRR)로만 잰다.
labels_chat.csv의 no_answer 행은 gold가 없으므로 채점 대상에서 빼고 top1만 관찰 기록한다.

사용:
  python run_eval_chat.py --api http://localhost:5000 --out chat_baseline_run1.jsonl --report chat_baseline_run1.md
"""
import argparse, json
from pathlib import Path
import pandas as pd
import requests


def parse_gold(raw) -> list[int]:
    if pd.isna(raw) or str(raw).strip() == "":
        return []
    return [int(x) for x in str(raw).split(";")]


def run(api, labels, out, top_k):
    df = pd.read_csv(labels, dtype=str)
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
        rec = {"id": row["id"], "question": row["question"], "style": row["style"]}
        gold_file = row.get("gold_source_file")
        gold_chunks = parse_gold(row.get("gold_chunk_index"))
        rec["gold_source_file"] = gold_file if isinstance(gold_file, str) else None
        rec["gold_chunk_index"] = gold_chunks
        try:
            r = requests.get(f"{api}/search", params={"query": row["question"], "top_k": top_k}, timeout=60)
            if r.status_code != 200:
                rec["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            else:
                d = r.json()
                rec["results"] = [
                    {"rank": i + 1, "source_file": h["source_file"],
                     "chunk_index": h.get("chunk_index"), "score": h["score"]}
                    for i, h in enumerate(d["results"])
                ]
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{row['id']:5s} {'ERR ' + rec['error'][:60] if 'error' in rec else 'ok'}", flush=True)


def score(out, report, top_k):
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "error" not in r]
    answerable = [r for r in ok if r["style"] != "no_answer"]
    no_answer = [r for r in ok if r["style"] == "no_answer"]

    def gold_rank(r):
        """gold_chunk_index 중 최상위 순위(1-indexed) 반환, 없으면 None."""
        golds = set(r["gold_chunk_index"])
        best = None
        for h in r.get("results", []):
            if h["source_file"] == r["gold_source_file"] and h["chunk_index"] in golds:
                if best is None or h["rank"] < best:
                    best = h["rank"]
        return best

    for r in answerable:
        r["_gold_rank"] = gold_rank(r)
        r["_mrr"] = (1.0 / r["_gold_rank"]) if r["_gold_rank"] else 0.0

    L = [f"# /chat retrieval baseline ({len(ok)}/{len(rows)}건 성공, top_k={top_k})\n"]

    def block(label, group):
        n = len(group)
        if not n:
            L.append(f"## {label} — 0건\n")
            return
        L.append(f"## {label} ({n}건)\n")
        L.append("| 지표 | 값 |\n|---|---|")
        for k in (1, 3, 5, 10):
            hit = sum(1 for r in group if r["_gold_rank"] and r["_gold_rank"] <= k)
            L.append(f"| hit@{k} | {hit}/{n} ({hit/n*100:.0f}%) |")
        mrr = sum(r["_mrr"] for r in group) / n
        L.append(f"| MRR | {mrr:.3f} |\n")

    block("전체 (colloquial+formal)", answerable)
    block("colloquial", [r for r in answerable if r["style"] == "colloquial"])
    block("formal", [r for r in answerable if r["style"] == "formal"])

    L.append("## 문항별 상세 (colloquial+formal)\n")
    L.append("| id | style | gold rank | gold score | top1 청크 | top1 score |")
    L.append("|---|---|---|---|---|---|")
    for r in answerable:
        hits = r.get("results", [])
        top1 = hits[0] if hits else {}
        gr = r["_gold_rank"]
        gscore = None
        if gr:
            gscore = next(h["score"] for h in hits if h["rank"] == gr)
        L.append(f"| {r['id']} | {r['style']} | {gr or '미포함'} | "
                 f"{f'{gscore:.4f}' if gscore is not None else '-'} | "
                 f"{top1.get('source_file')}#{top1.get('chunk_index')} | "
                 f"{top1.get('score', 0):.4f} |")

    missing = [r for r in answerable if not r["_gold_rank"]]
    L.append(f"\n## 미포함 (top_{top_k} 안에 gold 없음) — {len(missing)}건\n")
    for r in missing:
        L.append(f"- `{r['id']}` {r['question']!r} — gold={r['gold_chunk_index']}, "
                 f"top1={(r.get('results') or [{}])[0].get('source_file')}"
                 f"#{(r.get('results') or [{}])[0].get('chunk_index')}")

    L.append(f"\n## no_answer 관찰 ({len(no_answer)}건, 채점 안 함)\n")
    L.append("| id | question | top1 청크 | top1 score |")
    L.append("|---|---|---|---|")
    for r in no_answer:
        top1 = (r.get("results") or [{}])[0]
        L.append(f"| {r['id']} | {r['question']!r} | {top1.get('source_file')}#{top1.get('chunk_index')} | "
                 f"{top1.get('score', 0):.4f} |")

    if answerable:
        avg_ans_top1 = sum((r.get("results") or [{}])[0].get("score", 0) for r in answerable) / len(answerable)
        L.append(f"\n answerable 20건 top1 평균 score: {avg_ans_top1:.4f}")
    if no_answer:
        avg_na_top1 = sum((r.get("results") or [{}])[0].get("score", 0) for r in no_answer) / len(no_answer)
        L.append(f"no_answer 4건 top1 평균 score: {avg_na_top1:.4f}")

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
    p.add_argument("--labels", type=Path, default=Path(__file__).parent / "labels_chat.csv")
    p.add_argument("--out", type=Path, default=Path("chat_baseline_result.jsonl"))
    p.add_argument("--report", type=Path, default=Path("chat_baseline_report.md"))
    p.add_argument("--top_k", type=int, default=10)
    a = p.parse_args()

    try:
        requests.get(a.api, timeout=5)
    except Exception as e:
        raise SystemExit(f"앱에 연결 안 됨: {a.api}\n  {e}\n  앱이 떠 있는지 / 포트가 맞는지 확인.")

    run(a.api, a.labels, a.out, a.top_k)
    score(a.out, a.report, a.top_k)
