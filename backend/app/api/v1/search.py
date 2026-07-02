"""检索接口：GET /api/v1/search?q=xxx

支持参数：
    q: 查询文本（必填）
    top_k: 返回数量（1-20，默认 5）
    category: 分类过滤（可选）
    enable_rerank: 是否启用 rerank 精排（默认 true）
    enable_wiki: 是否启用 wiki 第三路检索（默认 false）

返回字段（含检索方式标签 + 元数据）：
    id, text, doc_id, category, college, subject, source_url, score,
    retrieval_sources, rerank_score, page_num, char_start, char_end

用法：
    curl -G "http://localhost:18000/api/v1/search" \
        --data-urlencode "q=导师" \
        --data-urlencode "top_k=5" \
        --data-urlencode "enable_rerank=true"
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.services.retrieval.hybrid_search import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


class SearchResultItem(BaseModel):
    """单条检索结果（含检索方式 + 元数据）"""
    id: int
    text: str
    doc_id: int | None = None
    category: str | None = None
    college: str | None = None
    subject: str | None = None
    source_url: str | None = None
    score: float
    retrieval_sources: list[str] = []        # ["dense","sparse"] / ["wiki"]
    rerank_score: float | None = None       # rerank 归一化分数
    page_num: int | None = None             # PDF 页码
    char_start: int | None = None           # 原文起始字符位置
    char_end: int | None = None             # 原文结束字符位置


class SearchResponse(BaseModel):
    """检索响应"""
    query: str
    total: int
    results: list[SearchResultItem]


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="查询文本"),
    top_k: int = Query(5, ge=1, le=50, description="返回数量"),
    category: str | None = Query(None, description="分类过滤（如 导师信息）"),
    enable_rerank: bool = Query(True, description="是否启用 rerank 精排"),
    enable_wiki: bool = Query(False, description="是否启用 wiki 第三路检索"),
    user=Depends(get_current_user),
):
    """混合检索：dense + sparse（+ 可选 wiki），RRF 融合，可选 rerank"""
    # 整个 hybrid_search（含 embed + milvus 检索 + rerank）放线程池，
    # 避免 reranker 推理阻塞事件循环导致 /health 端点超时无响应
    results = await asyncio.to_thread(
        hybrid_search,
        q,
        top_k=top_k,
        category=category,
        enable_rerank=enable_rerank,
        enable_wiki=enable_wiki,
    )
    return SearchResponse(
        query=q,
        total=len(results),
        results=[SearchResultItem(**r) for r in results],
    )
