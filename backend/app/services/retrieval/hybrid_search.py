"""Milvus hybrid search：dense HNSW + sparse BM25，RRF 融合，可选 rerank + wiki

检索流程：
    1. 用 BGE-M3 把 query 转成 dense + sparse 向量
    2. dense 路检索（HNSW + COSINE）
    3. sparse 路检索（SPARSE_INVERTED_INDEX + IP，等同 BM25）
    4. RRF（Reciprocal Rank Fusion）融合 dense + sparse 结果，记录每条命中来源
    5. 可选 rerank：用 bge-reranker-v2-m3 对 RRF top-K 候选精排
    6. 返回 top_k 结果，含 retrieval_sources / rerank_score / page_num 等元数据
    7. 可选 wiki 路结果附加在末尾（独立展示，不参与 RRF 融合，schema 与 chunks 不同）

RRF 公式：score(d) = sum( 1 / (k + rank_i(d)) )，k 默认 60
"""
from __future__ import annotations

from typing import Callable, Optional

from app.core.config import settings
from app.core.logging import logger
from app.services.ingestion.embedder import embed
from app.services.ingestion.milvus_writer import get_client

# RRF 参数
RRF_K = 60


def hybrid_search(
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
    enable_rerank: bool = True,
    enable_wiki: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """混合检索：dense + sparse（+ 可选 wiki），RRF 融合，可选 rerank

    Args:
        query: 查询文本
        top_k: 最终返回数量（rerank 后截断）
        category: 可选分类过滤（如 "导师信息"）
        enable_rerank: 是否启用 rerank 精排（候选数 > top_k 时生效）
        enable_wiki: 是否启用 wiki 第三路检索
        progress_callback: 可选回调，检索进入新阶段时调用（传阶段名：
            "embedding" / "dense" / "sparse" / "reranking"），用于 SSE 流式推送进度

    Returns:
        结果列表，每个元素是 dict：
            {
                "id": int,                  # milvus id
                "text": str,                # chunk 正文
                "doc_id": int,              # 关联 Document id
                "category": str,
                "college": str,
                "subject": str,
                "source_url": str,
                "score": float,             # 最终分数（rerank 后是 rerank 分数，否则 RRF 分数）
                "retrieval_sources": list[str],  # 命中来源 ["dense","sparse"] / ["wiki"] 等
                "rerank_score": float | None,    # rerank 归一化分数（未启用时 None）
                "page_num": int | None,     # PDF 页码（md 为 None）
                "char_start": int | None,    # 原文起始字符位置
                "char_end": int | None,      # 原文结束字符位置
            }
    """
    if not query or not query.strip():
        return []

    # 1. 向量化查询
    if progress_callback:
        progress_callback("embedding")
    embeddings = embed([query])
    query_dense = embeddings[0].dense
    query_sparse = embeddings[0].sparse

    client = get_client()
    collection = settings.milvus_collection_chunks

    # 构造过滤条件
    filter_expr = None
    if category:
        filter_expr = f'category == "{category}"'

    output_fields = [
        "text", "doc_id", "category", "college", "subject",
        "source_url", "page_num", "char_start", "char_end",
    ]
    # 候选集：下限 30 保召回，上限 50 防 top_k 大时候选爆炸
    # rerank 耗时随候选数线性增长（30 条约 36s），若用 max(top_k*6,30) 则
    # top_k=50 时候选 300、rerank 约 360s，故加上限 50 稳定在 36-60s
    search_limit = min(max(top_k * 2, 30), 50)

    logger.info(
        f"hybrid_search: query={query[:50]!r}, top_k={top_k}, "
        f"filter={filter_expr}, rerank={enable_rerank}, wiki={enable_wiki}"
    )

    # 2. dense 检索（HNSW + COSINE）
    if progress_callback:
        progress_callback("dense")
    dense_results = client.search(
        collection_name=collection,
        data=[query_dense],
        anns_field="dense",
        limit=search_limit,
        filter=filter_expr,
        output_fields=output_fields,
    )

    # 3. sparse 检索（SPARSE_INVERTED_INDEX + IP）
    if progress_callback:
        progress_callback("sparse")
    sparse_results = client.search(
        collection_name=collection,
        data=[query_sparse],
        anns_field="sparse",
        limit=search_limit,
        filter=filter_expr,
        output_fields=output_fields,
    )

    # 4. RRF 融合 + 记录每条命中来源
    rrf_scores: dict[int, float] = {}       # milvus_id -> rrf_score
    entity_map: dict[int, dict] = {}        # milvus_id -> entity
    sources_map: dict[int, set[str]] = {}   # milvus_id -> {来源标签}

    # dense 路的排名
    dense_hits = dense_results[0] if dense_results else []
    for rank, hit in enumerate(dense_hits):
        mid = hit["id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (RRF_K + rank + 1)
        entity_map[mid] = hit.get("entity", {})
        sources_map.setdefault(mid, set()).add("dense")

    # sparse 路的排名
    sparse_hits = sparse_results[0] if sparse_results else []
    for rank, hit in enumerate(sparse_hits):
        mid = hit["id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (RRF_K + rank + 1)
        entity_map[mid] = hit.get("entity", {})
        sources_map.setdefault(mid, set()).add("sparse")

    # wiki 路不参与 RRF 融合（schema 与 chunks 不同），结果在末尾独立附加
    # 见下方 "# wiki 路结果附加在末尾" 块

    logger.info(
        f"检索结果: dense={len(dense_hits)}, sparse={len(sparse_hits)}, "
        f"合并后 chunks={len(rrf_scores)}"
    )

    # 5. 按 RRF 排序，取候选集（候选数可能 > top_k，用于 rerank）
    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    candidate_items = sorted_ids[:search_limit]  # 候选集用于 rerank

    # 6. 可选 rerank：对候选集做精排
    rerank_applied = False
    if enable_rerank and len(candidate_items) > top_k:
        if progress_callback:
            progress_callback("reranking")
        try:
            from app.services.retrieval.reranker import rerank
            texts = [entity_map[mid].get("text", "") for mid in candidate_items]
            reranked = rerank(query, texts, top_k=top_k)
            # reranked: [(原索引(在 candidate_items 中), 分数)]
            candidate_items = [candidate_items[i] for i, _ in reranked]
            rerank_scores_map = {candidate_items[i]: reranked[i][1] for i in range(len(reranked))}
            rerank_applied = True
            logger.info(f"rerank 应用: {len(reranked)} 条精排结果")
        except Exception as e:
            logger.warning(f"rerank 失败，回退到 RRF 排序: {e}")
            candidate_items = sorted_ids[:top_k]
            rerank_scores_map = {}
    else:
        candidate_items = candidate_items[:top_k]
        rerank_scores_map = {}

    # 7. 构造返回结果
    results = []
    for mid in candidate_items:
        entity = entity_map.get(mid, {})
        if rerank_applied and mid in rerank_scores_map:
            final_score = round(rerank_scores_map[mid], 6)
            rerank_score = round(rerank_scores_map[mid], 6)
        else:
            final_score = round(rrf_scores[mid], 6)
            rerank_score = None

        results.append({
            "id": mid,
            "text": entity.get("text", ""),
            "doc_id": entity.get("doc_id"),
            "category": entity.get("category") or None,
            "college": entity.get("college") or None,
            "subject": entity.get("subject") or None,
            "source_url": entity.get("source_url") or None,
            "score": final_score,
            "retrieval_sources": sorted(sources_map.get(mid, set())),
            "rerank_score": rerank_score,
            "page_num": entity.get("page_num") if entity.get("page_num") is not None else None,
            "char_start": entity.get("char_start") if entity.get("char_start") is not None else None,
            "char_end": entity.get("char_end") if entity.get("char_end") is not None else None,
        })

    # wiki 路结果附加在末尾（独立展示，不与 chunks 混排）
    if enable_wiki:
        try:
            from app.services.wiki.searcher import search_wiki
            wiki_results = search_wiki(query, top_k=min(top_k, 3))
            for wr in wiki_results:
                wr["retrieval_sources"] = ["wiki"]
                wr["rerank_score"] = None
                wr["score"] = wr.get("score", 0.0)
                wr["doc_id"] = None
                wr["category"] = wr.get("entry_type")
                wr["college"] = None
                wr["subject"] = None
                wr["page_num"] = None
                wr["char_start"] = None
                wr["char_end"] = None
            results.extend(wiki_results)
        except Exception as e:
            logger.warning(f"wiki 结果附加失败: {e}")

    return results
