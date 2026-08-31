"""평가셋 채점 — 이미 떠 있는 앱에 HTTP로 쏜다.

사용:
  python run_eval.py --api http://localhost:8000

필요: requests, pandas.  레포/venv/도커 무관 — 앱만 떠 있으면 됨.
"""
import argparse, json
from pathlib import Path
import pandas as pd
import requests


SKIP_DIRS = {".venv", "venv", "site-packages", "__pycache__", "node_modules", ".git"}


def norm(v):
    if v in (None, ""):
        return None
    try:
        return int(float(str(v).replace(",", "").replace("원", "")))
    except ValueError:
        return None


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


def run(api, index, labels, out):
    df = pd.read_csv(labels, dtype=str).fillna("")
    # 실패한 건은 done에 넣지 않는다 — 재실행하면 자동 재시도
    done, keep = set(), []
    if out.exists():
        for l in out.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            d = json.loads(l)
            if "error" in d:
                continue          # 이 줄은 버리고 다시 시도
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
                rec["got"] = {
                    "is_receipt": d["extracted"].get("is_receipt"),
                    "amount": d["extracted"].get("amount"),
                    "date": d["extracted"].get("date"),
                    "vendor": d["extracted"].get("vendor"),
                    "sub_item": d["classification"].get("sub_item"),
                    "flag": d["classification"].get("flag"),
                    # 파이프라인 실제 필드명은 compliance_status, 값은 준수|위반의심|확인불가
                    "status": d["compliance"].get("compliance_status"),
                    "absolute_cap": (d["compliance"].get("absolute_cap") or {}).get("status"),
                    "sources": [s["source_file"] for s in d.get("sources", [])],
                }
                # 원인 분석용 원문 — 이거 없으면 왜 그렇게 판정했는지 못 봄
                rec["raw"] = {
                    # 분류가 맞춘 것 vs 컴플라이언스가 구제한 것을 구분하기 위한 필드
                    "flag_before_override": d["classification"].get("flag_before_override"),
                    "override_reason": d["classification"].get("override_reason"),
                    "override_rejected": d["compliance"].get("override_rejected"),
                    "cls_reasoning": d["classification"].get("reasoning"),
                    "cls_confidence": d["classification"].get("confidence"),
                    "comp_notes": d["compliance"].get("compliance_notes"),
                    "citation": d["compliance"].get("citation"),
                    "required_documents": d["compliance"].get("required_documents"),
                }
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
        # 라벨(ok/review/violation/unknown) -> 파이프라인 어휘(준수/위반의심/확인불가)
        STATUS_MAP = {"ok": "준수", "violation": "위반의심", "review": "확인불가", "unknown": "확인불가"}
        rec["want"] = {
            "amount": norm(row["amount"]), "date": row["date"],
            "sub_item": row["expected_sub_item"], "flag": row["expected_flag"],
            "status": STATUS_MAP.get(row["expected_status"], row["expected_status"]),
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{row['id']:5s} {'ERR ' + rec['error'][:60] if 'error' in rec else 'ok'}", flush=True)


def score(out, report):
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = [r for r in rows if "error" in r is False or "got" in r]
    n = len(ok)
    if not n:
        print("성공 0건 — 전부 실패"); return
    L = [f"# 평가 결과 ({n}/{len(rows)}건 성공)\n"]
    fp = [r for r in ok if r["got"].get("is_receipt") is False]
    if fp:
        L.append(f"## 🚨 is_receipt 오탐 {len(fp)}건 — 실제 영수증을 비영수증으로 거절함\n")
        for r in fp:
            L.append(f"- `{r['id']}` {r['file']}")
        L.append("")
    L += ["## 단계별 정확도\n", "| 항목 | 정확도 |", "|---|---|"]
    for key, cmp, label in [
        ("amount", lambda g, w: norm(g) == w and w is not None, "금액"),
        ("date", lambda g, w: str(g)[:10] == str(w)[:10] and w, "날짜"),
        ("sub_item", lambda g, w: str(g).strip() == str(w).strip(), "비목 분류"),
        ("flag", lambda g, w: str(g).strip() == str(w).strip(), "flag"),
        ("status", lambda g, w: str(g).strip() == str(w).strip(), "status"),
    ]:
        h = sum(1 for r in ok if cmp(r["got"].get(key), r["want"].get(key)))
        L.append(f"| {label} | {h}/{n} ({h/n*100:.0f}%) |")

    # 다수결 베이스라인 — 단일 클래스만 찍는 모델의 점수. 이걸 못 넘으면 성능이 아니다.
    from collections import Counter
    L.append("\n## 단일 클래스 수렴 검사 (제일 먼저 볼 것)\n")
    for key in ("flag", "sub_item", "status"):
        got_c = Counter(r["got"].get(key) for r in ok)
        want_c = Counter(r["want"].get(key) for r in ok)
        base = max(want_c.values()) / n
        acc = sum(1 for r in ok if str(r["got"].get(key)).strip() == str(r["want"].get(key)).strip()) / n
        verdict = "🚨 붕괴" if len(got_c) == 1 else ("⚠ 베이스라인 이하" if acc <= base else "✅")
        L.append(f"**{key}** {verdict}")
        L.append(f"- 모델 출력 종류 {len(got_c)}개: " + ", ".join(f"`{k}`×{v}" for k, v in got_c.most_common()))
        L.append(f"- 정확도 {acc*100:.0f}% / 다수결 베이스라인 {base*100:.0f}%"
                 f" → 순이득 {(acc-base)*100:+.0f}%p\n")

    # override 효과 — 분류가 스스로 맞춘 것과 컴플라이언스가 뒤집어준 것을 분리
    ov = [r for r in ok if (r.get("raw") or {}).get("flag_before_override")]
    if ov:
        good = [r for r in ov if r["got"]["flag"] == r["want"]["flag"]]
        bad = [r for r in ov if r["got"]["flag"] != r["want"]["flag"]]
        L.append(f"\n### override 효과: {len(ov)}건 발동 / 정답 {len(good)} · 오탐 {len(bad)}\n")
        for r in ov:
            mark = "✅" if r in good else "❌"
            L.append(f"{mark} `{r['id']}` {r['raw']['flag_before_override']} → {r['got']['flag']} "
                     f"(정답 {r['want']['flag']})")
            L.append(f"   근거: {str(r['raw'].get('override_reason'))[:140]}")
        if bad:
            L.append("\n**오탐이 있으면 금지 조항을 잘못 적용한 것 — 근거를 확인하라.**")
    else:
        L.append("\n### override 발동 0건 — 수정 B가 작동하지 않았다\n")

    # 게이트가 막은 건 — 이게 0이면 게이트가 아예 안 걸린 것
    rej = [r for r in ok if (r.get("raw") or {}).get("override_rejected")]
    L.append(f"\n### override 게이트 차단: {len(rej)}건\n")
    for r in rej:
        hit = "✅ 오탐 방지" if r["want"]["flag"] == "확인필요" else "🚨 정탐을 막음"
        L.append(f"{hit} `{r['id']}` (정답 {r['want']['flag']}, 최종 {r['got']['flag']})")
        L.append(f"   {str(r['raw']['override_rejected'])[:160]}")
    if not rej:
        L.append("(차단 0건 — 게이트가 발동하지 않았거나 LLM이 항상 올바른 조항을 인용했다)")

    L.append("### 클래스별 재현율\n| 클래스 | 정답 수 | 맞춘 수 | recall |\n|---|---|---|---|")
    recalls = []
    for cls in sorted({r["want"]["flag"] for r in ok}):
        tgt = [r for r in ok if r["want"]["flag"] == cls]
        hit = sum(1 for r in tgt if r["got"].get("flag") == cls)
        recalls.append(hit / len(tgt))
        L.append(f"| {cls} | {len(tgt)} | {hit} | {hit/len(tgt)*100:.0f}% |")
    # macro recall — 클래스 불균형에 안 속는 유일한 지표. 판정은 이걸로 한다.
    L.append(f"\n**macro recall = {sum(recalls)/len(recalls)*100:.0f}%** "
             f"(클래스별 recall 단순평균 — 다수 클래스에 눌리지 않는 값)")

    unsure = [r for r in ok if r["want"]["flag"] == "확인필요"]
    over = [r for r in unsure if r["got"].get("flag") in ("정상", "지원불가")]
    L.append("\n## 과신율 (핵심)\n")
    L.append(f"정답 `확인필요` {len(unsure)}건 중 단정: **{len(over)}건 "
             f"({len(over)/len(unsure)*100:.0f}%)**" if unsure else "해당 없음")
    for r in over:
        L.append(f"- `{r['id']}` → {r['got']['flag']} / {r['got']['sub_item']}")

    miss = [r for r in ok if r["want"]["flag"] == "지원불가" and r["got"].get("flag") != "지원불가"]
    L.append(f"\n## 놓친 지원불가: {len(miss)}건\n")
    for r in miss:
        L.append(f"- `{r['id']}` {r['file']} → {r['got'].get('flag')}")

    bad = [r for r in ok if norm(r["got"].get("amount")) != r["want"]["amount"]]
    L.append(f"\n## 금액 오류 {len(bad)}건\n| id | 라벨 | 모델 | 1↔7 오독? |\n|---|---|---|---|")
    for r in bad:
        w, g = r["want"]["amount"], norm(r["got"].get("amount"))
        # 라벨과 모델값이 앞자리 1/7만 다르면 라벨(OCR) 쪽이 틀렸을 가능성
        susp = "라벨 의심" if w and g and str(w)[1:] == str(g)[1:] and {str(w)[0], str(g)[0]} == {"1", "7"} else ""
        L.append(f"| {r['id']} | {w} | {g} | {susp} |")

    L.append("\n## 판정 근거 (원인 분석용)\n")
    for r in ok:
        if r["got"]["flag"] != r["want"]["flag"]:
            rr = r.get("raw", {})
            L.append(f"**{r['id']}** 라벨 `{r['want']['flag']}` → 모델 `{r['got']['flag']}` "
                     f"({rr.get('cls_confidence')})\n"
                     f"- 분류 근거: {str(rr.get('cls_reasoning'))[:200]}\n"
                     f"- 인용: {str(rr.get('citation'))[:150]}\n")

    err = [r for r in rows if "error" in r]
    if err:
        L.append(f"\n## 처리 실패 {len(err)}건\n")
        for r in err:
            L.append(f"- `{r['id']}` {r['error'][:120]}")

    report.write_text("\n".join(L), encoding="utf-8")
    print("\n" + "\n".join(L))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--labels", type=Path, default=Path(__file__).parent / "labels_prefilled.csv")
    p.add_argument("--images", type=Path, default=Path("."))
    p.add_argument("--out", type=Path, default=Path("eval_result.jsonl"))
    p.add_argument("--report", type=Path, default=Path("eval_report.md"))
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
                         f"  --images 를 사진들이 들어있는 상위 폴더로 지정하라.")

    run(a.api, index, a.labels, a.out)
    score(a.out, a.report)
