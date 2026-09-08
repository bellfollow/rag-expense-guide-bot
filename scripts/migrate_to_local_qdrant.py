"""
서버 모드 Qdrant → 로컬 모드(QdrantClient(path=...)) 마이그레이션.

scroll(with_vectors=True)로 서버에서 벡터·payload를 그대로 읽어 로컬 모드에 upsert만 한다.
Jina 재호출 없음(임베딩 재계산 안 함).

컬렉션 설정(벡터 차원/distance)은 서버 get_collection()으로 물어보지 않고
config.py의 VECTOR_DIM을 그대로 쓴다 — 서버(qdrant:latest)와 클라이언트(qdrant-client==1.7.3)
버전이 벌어져 있어 get_collection() 응답 파싱이 pydantic 검증 에러로 깨지는 걸 확인함
(scroll/upsert는 정상 동작, get_collection만 영향받음). distance는 embeddings.py의
init_collection()과 동일하게 Cosine 고정(현재 이 프로젝트에 다른 distance를 쓰는 곳 없음).
"""
import argparse
import sys

sys.path.insert(0, ".")

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, PointStruct, Distance
from config import VECTOR_DIM


def migrate(server_host: str, server_port: int, collection: str, local_path: str, batch_size: int = 200) -> int:
    server = QdrantClient(host=server_host, port=server_port)
    local = QdrantClient(path=local_path)

    print(f"컬렉션 설정(config.py 기준): size={VECTOR_DIM}, distance=Cosine")

    existing = [c.name for c in local.get_collections().collections]
    if collection not in existing:
        local.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        print(f"로컬 컬렉션 '{collection}' 생성")
    else:
        print(f"로컬 컬렉션 '{collection}' 이미 있음 — 재사용")

    total = 0
    offset = None
    while True:
        records, offset = server.scroll(
            collection_name=collection,
            with_payload=True,
            with_vectors=True,
            limit=batch_size,
            offset=offset,
        )
        if not records:
            break
        points = [PointStruct(id=r.id, vector=r.vector, payload=r.payload) for r in records]
        local.upsert(collection_name=collection, points=points)
        total += len(points)
        print(f"  {total}건 이관...")
        if offset is None:
            break

    return total


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--server-host", default="localhost")
    p.add_argument("--server-port", type=int, default=6333)
    p.add_argument("--collection", default="documents")
    p.add_argument("--local-path", default="./qdrant_data")
    a = p.parse_args()

    moved = migrate(a.server_host, a.server_port, a.collection, a.local_path)

    local = QdrantClient(path=a.local_path)
    local_count = local.count(a.collection).count
    print(f"\n이관 건수: {moved}")
    print(f"로컬 저장소 실제 count: {local_count}")
    print("일치" if moved == local_count else "!! 불일치 — 확인 필요")
