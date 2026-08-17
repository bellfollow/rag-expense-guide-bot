import uuid
import requests
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, FilterSelector,
)
from config import JINA_API_KEY, COLLECTION_NAME, VECTOR_DIM, qdrant_client, DEFAULT_DOC_TIER


JINA_EMBED_URL = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"


def embed_texts(texts: list[str], task: str = "retrieval.query") -> list[list[float]]:
    resp = requests.post(
        JINA_EMBED_URL,
        headers={"Authorization": f"Bearer {JINA_API_KEY}", "Content-Type": "application/json"},
        json={"model": JINA_MODEL, "task": task, "dimensions": VECTOR_DIM, "input": texts},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Jina 임베딩 실패: {resp.status_code} {resp.text[:200]}")
    return [d["embedding"] for d in resp.json()["data"]]


def init_collection() -> None:
    try:
        exists = any(
            c.name == COLLECTION_NAME
            for c in qdrant_client.get_collections().collections
        )
        if not exists:
            qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            print(f"✅ Collection '{COLLECTION_NAME}' created (dim={VECTOR_DIM})")
        else:
            print(f"✅ Collection '{COLLECTION_NAME}' already exists")
    except Exception as e:
        print(f"⚠️ Qdrant init error: {e}")


def get_stored_files() -> set[str]:
    try:
        result = qdrant_client.scroll(collection_name=COLLECTION_NAME, with_payload=True, limit=10000)
        return {p.payload.get("source_file", "") for p in result[0] if p.payload.get("source_file")}
    except Exception:
        return set()


def delete_chunks_for_file(filename: str) -> None:
    result = qdrant_client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=FilterSelector(
            filter=Filter(must=[FieldCondition(key="source_file", match=MatchValue(value=filename))])
        ),
    )
    print(f"🗑️ Deleted chunks for {filename}: {result}")


def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str, doc_tier: dict | None = None) -> int:
    doc_tier = doc_tier or DEFAULT_DOC_TIER
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "content": chunk,
                "source_file": filename,
                "chunk_index": idx,
                "char_count": len(chunk),
                "doc_tier": doc_tier["tier"],
                "doc_tier_label": doc_tier["label"],
                "doc_tier_rank": doc_tier["rank"],
            },
        )
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"✅ Stored {len(points)} vectors for {filename}")
    return len(points)


def set_doc_tier_for_file(filename: str, doc_tier: dict) -> None:
    """재임베딩 없이 특정 파일의 기존 포인트에 doc_tier 계열 payload만 갱신."""
    qdrant_client.set_payload(
        collection_name=COLLECTION_NAME,
        payload={
            "doc_tier": doc_tier["tier"],
            "doc_tier_label": doc_tier["label"],
            "doc_tier_rank": doc_tier["rank"],
        },
        points=Filter(must=[FieldCondition(key="source_file", match=MatchValue(value=filename))]),
    )
    print(f"✅ doc_tier updated for {filename}: {doc_tier['label']}")


def search(query_vector: list[float], top_k: int = 5) -> list:
    return qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
    )
