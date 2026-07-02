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
    # 新增分类字段（bwiki 风格分类导航用）
    category: str | None = None
    college: str | None = None
    subject: str | None = None


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
    # 新增分类字段（前端检索结果展示用）
    category: str | None = None
    college: str | None = None
    subject: str | None = None


class CollegeStat(BaseModel):
    """学院分组统计（左侧导航用）"""
    college: str
    count: int


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
    college: str | None = Query(None, description="学院过滤（bwiki 分类导航用）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Wiki 条目列表（分页 + 类型过滤 + 学院过滤）"""
    # 构造查询
    stmt = select(WikiEntry)
    count_stmt = select(func.count(WikiEntry.id))
    if entry_type:
        stmt = stmt.where(WikiEntry.entry_type == entry_type)
        count_stmt = count_stmt.where(WikiEntry.entry_type == entry_type)
    if college:
        stmt = stmt.where(WikiEntry.college == college)
        count_stmt = count_stmt.where(WikiEntry.college == college)

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
            # 新增分类字段
            category=e.category,
            college=e.college,
            subject=e.subject,
        )
        for e in result.scalars()
    ]

    return WikiListResponse(
        total=total, page=page, page_size=page_size, items=items
    )


@router.get("/search", response_model=WikiSearchResponse)
async def wiki_search(
    q: str = Query(..., min_length=1, description="查询文本"),
    top_k: int = Query(5, ge=1, le=50, description="返回数量"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Wiki 检索：title 模糊匹配优先 + Milvus dense 检索

    检索策略（两路合并去重）：
    1. title 模糊匹配：从 PG 查 title LIKE %q% 的条目（精确人名搜索优先）
    2. dense 检索：Milvus 语义相似度检索
    title 匹配的结果排前面（score=1.0），dense 结果排后面
    """
    # 1. title 模糊匹配（从 PG 查）
    title_stmt = (
        select(WikiEntry)
        .where(WikiEntry.title.ilike(f"%{q}%"))
        .order_by(WikiEntry.id)
        .limit(top_k)
    )
    title_result = await db.execute(title_stmt)
    title_entries = title_result.scalars().all()

    merged: list[dict] = []
    seen_titles: set[str] = set()
    for e in title_entries:
        merged.append({
            "id": e.id,
            "title": e.title,
            "entry_type": e.entry_type,
            "text": e.content_md,
            "summary": e.content_summary or "",
            "score": 1.0,
            "retrieval_sources": ["wiki_title"],
            # 新增分类字段
            "category": e.category,
            "college": e.college,
            "subject": e.subject,
        })
        seen_titles.add(e.title)

    # 2. dense 检索（Milvus），补充 title 匹配未覆盖的结果
    remaining = top_k - len(merged)
    if remaining > 0:
        dense_results = search_wiki(q, top_k=max(remaining, top_k))
        for r in dense_results:
            if r["title"] not in seen_titles:
                merged.append(r)
                seen_titles.add(r["title"])
            if len(merged) >= top_k:
                break

    return WikiSearchResponse(
        query=q,
        total=len(merged),
        results=[WikiSearchResultItem(**r) for r in merged[:top_k]],
    )


@router.get("/colleges", response_model=list[CollegeStat])
async def list_colleges(
    entry_type: str | None = Query(None, description="按类型过滤统计（person/policy/process）"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """返回所有学院及其条目数（bwiki 左侧分类导航用）

    按 entry_type 过滤后统计各学院条目数，按数量降序排列。
    """
    stmt = (
        select(WikiEntry.college, func.count(WikiEntry.id))
        .where(WikiEntry.college.isnot(None))
        .where(WikiEntry.college != "")
        .group_by(WikiEntry.college)
        .order_by(func.count(WikiEntry.id).desc())
    )
    if entry_type:
        stmt = stmt.where(WikiEntry.entry_type == entry_type)
    result = await db.execute(stmt)
    return [
        CollegeStat(college=r[0], count=r[1]) for r in result
    ]


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
        # 新增分类字段
        category=entry.category,
        college=entry.college,
        subject=entry.subject,
    )
