"""
임팩트 측정 스크립트
10개 질문 → /chat API → 응답시간/점수/답변 기록 → 결과 출력
"""
import time
import json
import requests

API_URL = "http://localhost:5000/chat"

QUESTIONS = [
    "A4용지 구입 영수증이 있는데 연구활동비로 처리할 수 있나?",
    "논문 게재료 50만원을 연구활동비에서 쓰려는데 한도가 있나?",
    "3천만원짜리 장비를 구입하려는데 사전 승인 절차는 어떻게 되나?",
    "연구원 해외 출장비는 어떤 항목까지 지원되나?",
    "연구비로 식사 접대를 할 수 있나? 가능하다면 한도는?",
    "과제 종료 후 남은 연구비는 어떻게 처리해야 하나?",
    "연구책임자가 갑자기 퇴직했을 때 과제는 어떻게 되나?",
    "연구비로 구입한 노트북을 개인 용도로 쓰면 어떻게 되나?",
    "인건비로 계상된 금액을 다른 비목으로 전용할 수 있나?",
    "정부 출연금 비율을 변경하고 싶을 때 어떤 절차를 거쳐야 하나?",
]

DIVIDER = "=" * 70


def confidence_label(sources):
    if not sources:
        return "OUT_OF_SCOPE"
    max_score = max(s["score"] for s in sources)
    if max_score >= 0.55:
        return "NORMAL"
    if max_score >= 0.45:
        return "WEAK"
    return "OUT_OF_SCOPE"


def run():
    results = []
    total_time = 0.0

    print(DIVIDER)
    print("AI 연구비 집행 챗봇 — 임팩트 측정")
    print(DIVIDER)

    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n[{i:02d}/{len(QUESTIONS)}] {q}")
        print("-" * 50)

        start = time.time()
        try:
            resp = requests.post(API_URL, data={"query": q, "top_k": 5}, timeout=60)
            elapsed = time.time() - start
            data = resp.json()

            sources = data.get("sources", [])
            max_score = max((s["score"] for s in sources), default=0.0)
            conf = confidence_label(sources)
            answer = data.get("answer", "")

            print(f"⏱  {elapsed:.1f}초  |  최고 score: {max_score:.3f}  |  신뢰도: {conf}")
            print(f"\n답변:\n{answer[:500]}{'...' if len(answer) > 500 else ''}")
            print("\n출처:")
            for s in sources:
                print(f"  {s['score']:.3f}  {s['source_file']} / {s.get('title','')[:50]}")

            results.append({
                "no": i,
                "question": q,
                "elapsed_sec": round(elapsed, 2),
                "max_score": round(max_score, 4),
                "confidence": conf,
                "answer_length": len(answer),
                "answer_preview": answer[:200],
                "sources_count": len(sources),
                "eval": "",  # 수기 평가: 맞음 / 부분 / 틀림 / 없음
            })

        except Exception as e:
            elapsed = time.time() - start
            print(f"❌ 오류: {e}")
            results.append({
                "no": i, "question": q,
                "elapsed_sec": round(elapsed, 2),
                "max_score": 0.0, "confidence": "ERROR",
                "answer_length": 0, "answer_preview": str(e),
                "sources_count": 0, "eval": "ERROR",
            })

        total_time += elapsed
        time.sleep(1)  # API 과부하 방지

    # 요약
    print(f"\n{DIVIDER}")
    print("요약")
    print(DIVIDER)

    normal  = sum(1 for r in results if r["confidence"] == "NORMAL")
    weak    = sum(1 for r in results if r["confidence"] == "WEAK")
    out     = sum(1 for r in results if r["confidence"] == "OUT_OF_SCOPE")
    avg_t   = total_time / len(results)
    avg_s   = sum(r["max_score"] for r in results) / len(results)

    print(f"총 질문:       {len(results)}개")
    print(f"신뢰도 NORMAL: {normal}개  WEAK: {weak}개  OUT/ERROR: {out}개")
    print(f"평균 응답시간: {avg_t:.1f}초")
    print(f"평균 최고 score: {avg_s:.3f}")
    print(f"총 소요시간:   {total_time:.1f}초")

    # JSON 저장
    import os
    from datetime import datetime
    os.makedirs("tests", exist_ok=True)
    out_path = f"tests/impact_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": {
            "total": len(results), "normal": normal, "weak": weak,
            "out_of_scope": out, "avg_elapsed_sec": round(avg_t, 2),
            "avg_max_score": round(avg_s, 4),
        }, "results": results}, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {out_path}")
    print("※ eval 컬럼에 맞음/부분/틀림/없음 수기 입력 후 최종 정확도 계산")


if __name__ == "__main__":
    run()
