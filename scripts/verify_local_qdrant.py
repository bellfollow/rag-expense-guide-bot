"""
서버 모드 vs 로컬 모드 Qdrant 검색 결과 동일성 검증.
Jina 임베딩은 쿼리당 1회만 호출하고, 같은 벡터로 양쪽에 검색해 비교한다.

사용:
  python scripts/verify_local_qdrant.py "소모품비 사용 기준"
  python scripts/verify_local_qdrant.py "소모품비 사용 기준" --local-path ./qdrant_data
"""
import argparse
import sys

sys.path.insert(0, ".")

from qdrant_client import QdrantClient
from embeddings import embed_texts  # Jina 호출만 재사용, qdrant_client는 이 스크립트에서 직접 만든다


def main():
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--server-host", default="localhost")
    p.add_argument("--server-port", type=int, default=6333)
    p.add_argument("--collection", default="documents")
    p.add_argument("--local-path", default="./qdrant_data")
    p.add_argument("--top-k", type=int, default=5)
    a = p.parse_args()

    vector = embed_texts([a.query], task="retrieval.query")[0]

    server = QdrantClient(host=a.server_host, port=a.server_port)
    local = QdrantClient(path=a.local_path)

    server_hits = server.search(collection_name=a.collection, query_vector=vector, limit=a.top_k)
    local_hits = local.search(collection_name=a.collection, query_vector=vector, limit=a.top_k)

    print(f"쿼리: {a.query!r}\n")
    print(f"{'순위':<4} {'서버 id':<38} {'서버 score':<12} {'로컬 id':<38} {'로컬 score'}")
    same_order = True
    for i in range(max(len(server_hits), len(local_hits))):
        s = server_hits[i] if i < len(server_hits) else None
        l = local_hits[i] if i < len(local_hits) else None
        s_id = str(s.id) if s else "-"
        l_id = str(l.id) if l else "-"
        s_score = f"{s.score:.4f}" if s else "-"
        l_score = f"{l.score:.4f}" if l else "-"
        if s_id != l_id:
            same_order = False
        print(f"{i+1:<4} {s_id:<38} {s_score:<12} {l_id:<38} {l_score}")

    print("\nid 순서/구성 완전 일치" if same_order else "\n!! id 순서 또는 구성 불일치")


if __name__ == "__main__":
    main()
