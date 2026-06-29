"""Wiki 检索器：在 Milvus wiki 集合做 dense 检索

wiki 集合 schema（见 infra/scripts/init_milvus.py）：
    id INT64 auto_id primary
    dense FLOAT_VECTOR(1024)
    title VARCHAR(255)
    entry_type VARCHAR(32)   # person/policy/process
    content VARCHAR(32768)
    summary VARCHAR(1024)

用法：
    from app.services.wiki.searcher import search_wiki
    results = search_wiki("导师信息", top_k=3)
"""
from __future__ import annotations

from app.core.config import settings
from app.core.logging import logger
from app.services.ingestion.embedder import embed
from app.services.ingestion.milvus_writer import get_client


def search_wiki(query: str, top_k: int = 3) -> list[dict]:
    """在 wiki 集合做 dense 检索

    Args:
        query: 查询文本
        top_k: 返回数量

    Returns:
        list[dict]，每个元素含：
            id, title, entry_type, text(=content), summary, score, retrieval_sources=["wiki"]
    """
    if not query or not query.strip():
        return []

    # 用 BGE-M3 计算 query 的 dense 向量（只需要 dense，不需要 sparse）
    embeddings = embed([query])
    query_dense = embeddings[0].dense

    client = get_client()
    collection = settings.milvus_collection_wiki

    logger.info(f"search_wiki: query={query[:50]!r}, top_k={top_k}")

    results = client.search(
        collection_name=collection,
        data=[query_dense],
        anns_field="dense",
        limit=top_k,
        output_fields=["title", "entry_type", "content", "summary"],
    )

    if not results or not results[0]:
        logger.info("search_wiki: 无结果")
        return []

    out: list[dict] = []
    for hit in results[0]:
        entity = hit.get("entity", {})
        out.append({
            "id": hit["id"],
            "title": entity.get("title", ""),
            "entry_type": entity.get("entry_type", ""),
            "text": entity.get("content", ""),
            "summary": entity.get("summary", ""),
            # COSINE 距离：distance 越大越相似（pymilvus 已归一化）
            "score": round(float(hit.get("distance", 0.0)), 6),
            "retrieval_sources": ["wiki"],
        })

    logger.info(f"search_wiki 完成: 命中 {len(out)} 条")
    return out
