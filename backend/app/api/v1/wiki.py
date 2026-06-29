"""Wiki 管理 API

端点：
    POST /api/v1/wiki/generate  触发生成（admin 权限）
    GET  /api/v1/wiki            列表（分页 + entry_type 过滤）
    GET  /api/v1/wiki/{id}       单条详情
    GET  /api/v1/wiki/search?q=  在 wiki 集合做 dense 检索

用法：
    # 触发生成
    curl -X POST -H "Authorization: Bearer <token>" \\
        -H "Content-Type: application/json" \\
        -d '{"limit":50}' \\
        http://localhost:18000/api/v1/wiki/generate

    # 查列表
    curl -H "Authorization: Bearer <token>" \\
        "http://localhost:18000/api/v1/wiki?entry_type=person&page=1&page_size=20"

    # 在 wiki 集合检索
    curl -G "http://localhost:18000/api/v1/wiki/search" \\
        --data-urlencode "q=导师" --data-urlencode "top_k=5"
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, get_current_user
from app.core.logging import logger
from app.db.session import get_session
from app.models.wiki import WikiEntry
from app.services.wiki.generator import generate_wiki_entries
from app.services.wiki.searcher import search_wiki

router = APIRouter(prefix="/wiki", tags=["wiki"])


class WikiGenerateRequest(BaseModel):
    """Wiki 生成请求"""
    doc_ids: list[int] | None = Field(
        None, description="限定从哪些 document 提取（不传则全部）"
    )
    limit: int = Field(50, ge=1, le=500, description="处理 chunk 数量上限")


class WikiGenerateResponse(BaseModel):
    """Wiki 生成响应"""
    generated: int
    skipped: int
    errors: int


class WikiItem(BaseModel):
    """Wiki 条目（列表/详情）"""
    id: int
    title: str
    entry_type: str
    content_md: str
    content_summary: str | None = None
    source_doc_ids: list[int] | None = None
    mention_count: int
    version: int


class WikiListResponse(BaseModel):
    """Wiki 列表响应"""
    total: int
    page: int
    page_size: int
    items: list[WikiItem]


class WikiSearchResultItem(BaseModel):
    """Wiki 检索单条结果"""
    id: int
    title: str
    entry_type: str
    text: str
    summary: str
    score: float
    retrieval_sources: list[str] = ["wiki"]


class WikiSearchResponse(BaseModel):
    """Wiki 检索响应"""
    query: str
    total: int
    results: list[WikiSearchResultItem]


@router.post("/generate", response_model=WikiGenerateResponse)
async def generate(
    req: WikiGenerateRequest,
    admin=Depends(get_current_admin),
):
    """触发 Wiki 生成（仅 admin）"""
    logger.info(f"wiki 生成请求: doc_ids={req.doc_ids}, limit={req.limit}")
    stats = await generate_wiki_entries(doc_ids=req.doc_ids, limit=req.limit)
    return WikiGenerateResponse(**stats)


@router.get("", response_model=WikiListResponse)
async def list_wiki(
    entry_type: str | None = Query(None, description="类型过滤 person/policy/process"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Wiki 条目列表（分页 + 类型过滤）"""
    # 构造查询
    stmt = select(WikiEntry)
    count_stmt = select(func.count(WikiEntry.id))
    if entry_type:
        stmt = stmt.where(WikiEntry.entry_type == entry_type)
        count_stmt = count_stmt.where(WikiEntry.entry_type == entry_type)

    # 总数
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页
    stmt = stmt.order_by(WikiEntry.id.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size)
    result = await db.execute(stmt)
    items = [
        WikiItem(
            id=e.id,
            title=e.title,
            entry_type=e.entry_type,
            content_md=e.content_md,
            content_summary=e.content_summary,
            source_doc_ids=e.source_doc_ids,
            mention_count=e.mention_count,
            version=e.version,
        )
        for e in result.scalars()
    ]

    return WikiListResponse(
        total=total, page=page, page_size=page_size, items=items
    )


@router.get("/search", response_model=WikiSearchResponse)
async def wiki_search(
    q: str = Query(..., min_length=1, description="查询文本"),
    top_k: int = Query(5, ge=1, le=20, description="返回数量"),
    user=Depends(get_current_user),
):
    """在 Milvus wiki 集合做 dense 检索"""
    results = search_wiki(q, top_k=top_k)
    return WikiSearchResponse(
        query=q,
        total=len(results),
        results=[WikiSearchResultItem(**r) for r in results],
    )


@router.get("/{entry_id}", response_model=WikiItem)
async def get_wiki(
    entry_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Wiki 条目详情"""
    entry = await db.get(WikiEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Wiki 条目不存在")
    return WikiItem(
        id=entry.id,
        title=entry.title,
        entry_type=entry.entry_type,
        content_md=entry.content_md,
        content_summary=entry.content_summary,
        source_doc_ids=entry.source_doc_ids,
        mention_count=entry.mention_count,
        version=entry.version,
    )
