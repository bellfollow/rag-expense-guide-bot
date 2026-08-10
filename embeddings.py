import uuid
import requests
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, FilterSelector,
)
from config import JINA_API_KEY, COLLECTION_NAME, VECTOR_DIM, qdrant_client


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


def store_chunks(chunks: list[str], embeddings: list[list[float]], filename: str) -> int:
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=embedding,
            payload={
                "content": chunk,
                "source_file": filename,
                "chunk_index": idx,
                "char_count": len(chunk),
            },
        )
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"✅ Stored {len(points)} vectors for {filename}")
    return len(points)


def search(query_vector: list[float], top_k: int = 5) -> list:
    return qdrant_client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
    )
