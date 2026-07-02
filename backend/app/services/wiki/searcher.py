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

    # 全量遍历（统计类查询用）
    from app.services.wiki.searcher import list_wiki_entries_by_type
    entries = await list_wiki_entries_by_type("person")
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import logger
from app.db.session import session_scope
from app.models.wiki import WikiEntry
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
        output_fields=["title", "entry_type", "content", "summary", "category", "college", "subject"],
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
            # 新增分类字段（前端 bwiki 分类展示用）
            "category": entity.get("category", ""),
            "college": entity.get("college", ""),
            "subject": entity.get("subject", ""),
            # COSINE 距离：distance 越大越相似（pymilvus 已归一化）
            "score": round(float(hit.get("distance", 0.0)), 6),
            "retrieval_sources": ["wiki"],
        })

    logger.info(f"search_wiki 完成: 命中 {len(out)} 条")
    return out


async def list_wiki_entries_by_type(
    entry_type: str, limit: int = 2000
) -> list[dict]:
    """从 PG 全量读取指定类型的 wiki 条目（统计类查询用）

    与 search_wiki 的区别：
    - search_wiki 做 Milvus dense 相似度检索，返回 top_k 条
    - 本方法从 PG 全量读取，不做相似度过滤，用于统计/聚合类查询

    Args:
        entry_type: 条目类型（person/policy/process）
        limit: 读取上限（防止数据量过大）

    Returns:
        list[dict]，每个元素含：
            id, title, entry_type, content_md, content_summary,
            source_doc_ids, retrieval_sources=["wiki_stats"]
    """
    logger.info(f"list_wiki_entries_by_type: type={entry_type}, limit={limit}")

    async with session_scope() as s:
        stmt = (
            select(WikiEntry)
            .where(WikiEntry.entry_type == entry_type)
            .order_by(WikiEntry.id)
            .limit(limit)
        )
        result = await s.execute(stmt)
        entries = result.scalars().all()

    out: list[dict] = []
    for e in entries:
        out.append({
            "id": e.id,
            "title": e.title,
            "entry_type": e.entry_type,
            "content_md": e.content_md,
            "content_summary": e.content_summary or "",
            "source_doc_ids": e.source_doc_ids or [],
            "retrieval_sources": ["wiki_stats"],
        })

    logger.info(f"list_wiki_entries_by_type 完成: 读取 {len(out)} 条")
    return out
