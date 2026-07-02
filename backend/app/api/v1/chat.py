"""RAG 问答接口：POST /api/v1/chat

增强流程（多轮对话 + 意图识别 + rerank）：
    1. 解析/创建 conversation
    2. 写入 user message
    3. 拉历史消息（最近 4 轮）
    4. 意图识别 + query 改写（代词消解）
    5. 用改写后的 query 调 hybrid_search 检索 top_k 相关 chunk
    6. 拼 prompt（含 history + context + intent 提示）
    7. 调用 DeepSeek（main_model v4-flash）生成答案
    8. 写入 assistant message（含 trace）
    9. 返回答案 + sources + conversation_id + intent + rewritten_query

用法：
    # 第 1 轮（无 conversation_id）
    curl -X POST -H "Content-Type: application/json" \
        -d '{"question":"导师信息怎么查？","top_k":5}' \
        http://localhost:18000/api/v1/chat

    # 第 2 轮（带 conversation_id，验证代词消解）
    curl -X POST -H "Content-Type: application/json" \
        -d '{"question":"他需要哪些材料？","conversation_id":1,"top_k":5}' \
        http://localhost:18000/api/v1/chat
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import logger
from app.db.session import get_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.llm.deepseek_client import get_llm_client
from app.services.llm.intent_recognition import COMBINE_ANSWERS_PROMPT, recognize_intent
from app.services.llm.prompt_builder import (
    build_rag_prompt,
    build_stats_prompt,
    build_stats_aggregate_prompt,
)
from app.services.retrieval.hybrid_search import hybrid_search
from app.services.wiki.searcher import list_wiki_entries_by_type

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, description="用户问题")
    top_k: int = Field(5, ge=1, le=50, description="检索 chunk 数量")
    conversation_id: int | None = Field(
        None, description="会话 ID（不传则新建会话，多轮对话用）"
    )
    enable_rerank: bool = Field(True, description="是否启用 rerank 精排（reranker 模型未就绪时可关闭）")
    enable_wiki: bool = Field(False, description="是否启用 wiki 第三路检索")


class ChatSource(BaseModel):
    """引用来源（含检索方式 + 元数据）"""
    text: str
    score: float
    doc_id: int | None = None
    category: str | None = None
    college: str | None = None
    subject: str | None = None
    source_url: str | None = None
    retrieval_sources: list[str] = []        # 检索方式 ["dense","sparse"] / ["wiki"]
    rerank_score: float | None = None        # rerank 归一化分数
    page_num: int | None = None              # PDF 页码
    char_start: int | None = None            # 原文起始字符位置
    char_end: int | None = None              # 原文结束字符位置


class ChatResponse(BaseModel):
    """问答响应"""
    question: str                           # 原始问题
    rewritten_query: str                    # 改写后的问题（代词消解）
    intent: str                             # 意图标签
    conversation_id: int                    # 会话 ID（用于后续多轮）
    answer: str
    sources: list[ChatSource]


# 保留原 PROMPT_TEMPLATE（已弃用，改用 prompt_builder.build_rag_prompt）
# 保留是为了兼容历史代码引用与文档说明
LEGACY_PROMPT_TEMPLATE = """你是一个研究生院知识库助手。请基于以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实说明，不要编造。
回答时请引用资料来源（如"根据导师信息..."）。

参考资料：
{context}

用户问题：{question}

回答："""


# 统计类查询的意图标签
STATS_INTENT = "统计查询"


async def _handle_multi_questions(
    sub_questions: list[str],
    history: list[dict],
    top_k: int,
    db: AsyncSession,
) -> tuple[str, list[dict], dict]:
    """处理多问题拆解：逐个子问题检索+生成，最后合并答案

    Args:
        sub_questions: 拆解后的子问题列表
        history: 历史对话
        top_k: 每个子问题的检索数量
        db: 数据库会话

    Returns:
        (answer, results, trace)
    """
    logger.info(f"多问题拆解: 共 {len(sub_questions)} 个子问题")

    answers_parts: list[str] = []
    all_retrieved: list[dict] = []
    combined_trace: dict = {
        "retrieved": [],
        "wiki_used": False,
        "intent": "多问题",
        "sub_questions": sub_questions,
    }

    for i, sq in enumerate(sub_questions, 1):
        logger.info(f"处理子问题 [{i}/{len(sub_questions)}]: {sq[:50]!r}")

        try:
            # 识别子问题的意图
            sq_intent_result = await recognize_intent(sq, history)
            sq_intent = sq_intent_result["intent"]
            sq_rewritten = sq_intent_result["rewritten_query"]

            # 根据意图选择检索方式
            if sq_intent == STATS_INTENT:
                sub_answer, sub_results, _ = await _handle_stats_query(
                    rewritten_query=sq_rewritten,
                    intent=sq_intent,
                    history=history,
                    top_k=top_k,
                    db=db,
                )
            else:
                sub_results = await asyncio.to_thread(
                    hybrid_search,
                    sq_rewritten,
                    top_k=top_k,
                    enable_rerank=False,
                    enable_wiki=False,
                )
                if not sub_results:
                    sub_answer = f"未检索到与「{sq}」相关的资料。"
                else:
                    prompt = build_rag_prompt(
                        question=sq_rewritten,
                        context=sub_results,
                        history=history,
                        intent=sq_intent,
                    )
                    sub_answer = await get_llm_client().generate(
                        prompt, model=settings.deepseek_main_model
                    )

            answers_parts.append(f"### {sq}\n\n{sub_answer}")
            all_retrieved.extend(sub_results or [])

            # 累计 trace 的 retrieved
            for r in sub_results or []:
                combined_trace["retrieved"].append({
                    "doc_id": r.get("doc_id"),
                    "score": r.get("score"),
                    "retrieval_sources": r.get("retrieval_sources", []),
                })

        except Exception as e:
            logger.error(f"子问题 [{i}] 处理失败: {e}")
            answers_parts.append(f"### {sq}\n\n处理该问题时出现错误：{e}")

    # 合并答案
    if len(answers_parts) == 1:
        final_answer = answers_parts[0]
    else:
        # 用 LLM 合并多个子答案
        answers_block = "\n\n---\n\n".join(answers_parts)
        combine_prompt = COMBINE_ANSWERS_PROMPT.format(answers_block=answers_block)
        try:
            final_answer = await get_llm_client().generate(
                combine_prompt, model=settings.deepseek_main_model
            )
        except Exception:
            # 合并失败，直接拼接
            final_answer = "\n\n".join(answers_parts)

    # 去重 results
    seen_ids = set()
    unique_results = []
    for r in all_retrieved:
        rid = r.get("id") or r.get("doc_id")
        if rid not in seen_ids:
            seen_ids.add(rid)
            unique_results.append(r)

    logger.info(f"多问题处理完成: {len(answers_parts)} 个子问题, {len(unique_results)} 条检索结果")
    return final_answer, unique_results, combined_trace


async def _handle_stats_query(
    rewritten_query: str,
    intent: str,
    history: list[dict],
    top_k: int,
    db: AsyncSession,
) -> tuple[str, list[dict], dict]:
    """处理统计类查询：三层策略，SQL 聚合优先

    统计类问题（如"一共有多少导师"）需要全量数据做聚合。三层兜底策略：
    1. 【优先】SQL 聚合查询：COUNT/GROUP BY 算好数字让 LLM 润色（真统计，无幻觉）
    2. 【兜底1】拉全量 mentor 文本：让 LLM 数数（伪统计，mentors 表有数据时用）
    3. 【兜底2】wiki person 条目：让 LLM 数数（mentors 表为空时用）

    Args:
        rewritten_query: 改写后的查询（无代词）
        intent: 意图标签
        history: 历史对话
        top_k: sources 展示数量上限
        db: 数据库会话

    Returns:
        (answer, results, trace)
    """
    # 优先：SQL 聚合查询（真统计，让 LLM 润色而非数数）
    try:
        aggregates = await _get_mentor_aggregates(db)
    except Exception as e:
        logger.error(f"SQL 聚合查询失败，回退到 _get_mentor_stats: {e}")
        aggregates = {}

    if aggregates:
        prompt = build_stats_aggregate_prompt(
            question=rewritten_query,
            aggregates=aggregates,
            history=history,
            intent=intent,
        )
        answer = await get_llm_client().generate(
            prompt, model=settings.deepseek_main_model
        )

        # 用聚合统计的 top 学院作为 sources（展示给用户）
        top_colleges = aggregates.get("by_college", [])[: top_k if top_k else 5]
        results = [
            {
                "text": f"{g['key']}：{g['count']} 人",
                "title": g["key"],
                "score": 1.0,
                "retrieval_sources": ["mentor_aggregates"],
            }
            for g in top_colleges
        ]
        trace = {
            "retrieved": [
                {"doc_id": None, "score": 1.0, "retrieval_sources": ["mentor_aggregates"]}
                for _ in results
            ],
            "wiki_used": False,
            "wiki_stats": False,
            "mentor_stats": True,
            "mentor_aggregates": True,
            "mentor_total": aggregates.get("total", 0),
            "by_college_count": len(aggregates.get("by_college", [])),
            "by_title_count": len(aggregates.get("by_title", [])),
            "by_subject_count": len(aggregates.get("by_subject", [])),
            "intent": intent,
            "rewritten_query": rewritten_query,
        }
        logger.info(
            f"统计查询完成(SQL 聚合): total={aggregates.get('total')}, "
            f"colleges={len(aggregates.get('by_college', []))}, "
            f"titles={len(aggregates.get('by_title', []))}, "
            f"answer_len={len(answer)}"
        )
        return answer, results, trace

    # 兜底1：拉全量 mentor 文本（伪统计，让 LLM 数数）
    mentor_stats = await _get_mentor_stats(db)

    if mentor_stats:
        # 有 mentor 数据，用结构化数据做统计
        prompt = build_stats_prompt(
            question=rewritten_query,
            wiki_entries=mentor_stats,
            history=history,
            intent=intent,
        )
        answer = await get_llm_client().generate(
            prompt, model=settings.deepseek_main_model
        )

        results = [
            {
                "text": e["content_md"][:500],
                "title": e["title"],
                "score": 1.0,
                "retrieval_sources": ["mentor_stats"],
            }
            for e in mentor_stats[:top_k]
        ]
        trace = {
            "retrieved": [
                {"doc_id": None, "score": 1.0, "retrieval_sources": ["mentor_stats"]}
                for _ in results
            ],
            "wiki_used": False,
            "wiki_stats": False,
            "mentor_stats": True,
            "mentor_total": len(mentor_stats),
            "intent": intent,
            "rewritten_query": rewritten_query,
        }
        logger.info(
            f"统计查询完成(mentor): total={len(mentor_stats)}, "
            f"answer_len={len(answer)}"
        )
        return answer, results, trace

    # 回退到 wiki person 条目
    wiki_entries = await list_wiki_entries_by_type("person")

    if not wiki_entries:
        answer = "知识库中暂无导师条目，无法统计。请先摄入导师数据并生成 wiki。"
        trace = {
            "retrieved": [],
            "wiki_used": False,
            "wiki_stats": True,
            "intent": intent,
            "rewritten_query": rewritten_query,
        }
        return answer, [], trace

    prompt = build_stats_prompt(
        question=rewritten_query,
        wiki_entries=wiki_entries,
        history=history,
        intent=intent,
    )
    answer = await get_llm_client().generate(
        prompt, model=settings.deepseek_main_model
    )

    results = [
        {
            "text": e["content_md"][:500],
            "title": e["title"],
            "score": 1.0,
            "retrieval_sources": ["wiki_stats"],
        }
        for e in wiki_entries[:top_k]
    ]
    trace = {
        "retrieved": [
            {"doc_id": None, "score": 1.0, "retrieval_sources": ["wiki_stats"]}
            for _ in results
        ],
        "wiki_used": True,
        "wiki_stats": True,
        "wiki_total": len(wiki_entries),
        "intent": intent,
        "rewritten_query": rewritten_query,
    }
    logger.info(
        f"统计查询完成(wiki): wiki_total={len(wiki_entries)}, "
        f"answer_len={len(answer)}"
    )
    return answer, results, trace


async def _get_mentor_stats(db: AsyncSession) -> list[dict]:
    """从 Mentor + MentorIdentity 表聚合导师统计数据

    返回与 wiki_entries 格式兼容的 dict 列表，供 build_stats_prompt 使用。
    如果 mentors 表为空则返回空列表。
    """
    from app.models.mentor import Mentor, MentorIdentity

    stmt = select(Mentor).order_by(Mentor.id).limit(2000)
    result = await db.execute(stmt)
    mentors = result.scalars().all()

    if not mentors:
        return []

    out: list[dict] = []
    for m in mentors:
        # 聚合该导师的所有身份信息
        identities = await db.execute(
            select(MentorIdentity).where(MentorIdentity.mentor_id == m.id)
        )
        ident_list = identities.scalars().all()

        colleges = list({i.college for i in ident_list if i.college})
        subjects = list({i.subject_direction for i in ident_list if i.subject_direction})
        titles = list({i.title for i in ident_list if i.title})

        # 构造 content_md：结构化展示导师信息
        parts = [f"姓名：{m.name}"]
        if m.birth_year:
            parts.append(f"出生年份：{m.birth_year}")
        if m.gender:
            parts.append(f"性别：{m.gender}")
        if colleges:
            parts.append(f"所属学院：{', '.join(colleges)}")
        if subjects:
            parts.append(f"学科方向：{', '.join(subjects)}")
        if titles:
            parts.append(f"职称：{', '.join(titles)}")

        content_md = "；".join(parts)
        content_summary = f"{m.name}"
        if colleges:
            content_summary += f"，{colleges[0]}"
        if titles:
            content_summary += f"，{titles[0]}"

        out.append({
            "id": m.id,
            "title": m.name,
            "entry_type": "person",
            "content_md": content_md,
            "content_summary": content_summary,
            "source_doc_ids": [],
            "retrieval_sources": ["mentor_stats"],
        })

    return out


async def _get_mentor_aggregates(db: AsyncSession) -> dict:
    """SQL 聚合查询导师统计数据（真统计，非 LLM 数数）

    用 COUNT(DISTINCT mentor_id) 避免一个导师多个 identity 导致重复计数。
    返回结构供 build_stats_aggregate_prompt 使用：
        {
            "total": int,
            "by_college": [{"key": str, "count": int}, ...],
            "by_title": [{"key": str, "count": int}, ...],
            "by_subject": [{"key": str, "count": int}, ...],
        }

    如果 mentors 表为空则返回空 dict（调用方据此回退到 _get_mentor_stats）。

    注意：title 字段是自由文本（如"教授/博导"可能写在一起），group_by(title)
    会出现"教授"和"教授/博导"两个组，由 LLM 在润色时自行合并处理。
    """
    from app.models.mentor import Mentor, MentorIdentity

    # 导师总数（去重，直接 COUNT mentors 表）
    total_result = await db.execute(select(func.count(Mentor.id)))
    total = total_result.scalar() or 0
    if total == 0:
        return {}

    async def _group_count(field, group_expr=None) -> list[dict]:
        """按指定字段分组统计 DISTINCT mentor_id 数量，按数量降序

        Args:
            field: 用于 WHERE 过滤的字段（过滤 NULL/空串）
            group_expr: 用于 SELECT/GROUP BY 的表达式，默认=field。
                可传入清洗后的表达式，如对 title 用 regexp_replace
                去掉 markdown 残留（'** 教授' → '教授'）。
        """
        if group_expr is None:
            group_expr = field
        stmt = (
            select(group_expr, func.count(func.distinct(MentorIdentity.mentor_id)))
            .where(field.isnot(None))
            .where(field != "")
            .group_by(group_expr)
            .order_by(func.count(func.distinct(MentorIdentity.mentor_id)).desc())
        )
        rows = (await db.execute(stmt)).all()
        return [{"key": k, "count": int(c)} for k, c in rows if k]

    by_college = await _group_count(MentorIdentity.college)
    # title 字段有 markdown 残留（如 '** 教授'），用正则去掉开头的 * 和空白后分组
    # 正则 '^[*]+[[:space:]]*' 锚定开头，匹配一个或多个 * 加可选空白
    # 清洗后 '** 教授'(20人) 会并入 '教授'(254人)，分组更干净
    cleaned_title = func.regexp_replace(
        MentorIdentity.title, '^[*]+[[:space:]]*', ''
    )
    by_title = await _group_count(MentorIdentity.title, group_expr=cleaned_title)
    by_subject = await _group_count(MentorIdentity.subject_direction)

    return {
        "total": int(total),
        "by_college": by_college,
        "by_title": by_title,
        "by_subject": by_subject,
    }


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """RAG 问答：意图识别 + 检索 + 生成（支持多轮对话）"""
    logger.info(
        f"chat 请求: question={req.question[:50]!r}, "
        f"top_k={req.top_k}, conv_id={req.conversation_id}"
    )

    # 1. 解析/创建 conversation
    if req.conversation_id:
        conv = await db.get(Conversation, req.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if conv.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问该会话")
    else:
        conv = Conversation(
            user_id=user.id,
            title=req.question[:50],
        )
        db.add(conv)
        await db.flush()

    # 2. 写 user message
    user_msg = Message(
        conversation_id=conv.id,
        role="user",
        content=req.question,
    )
    db.add(user_msg)
    await db.flush()

    # 3. 拉历史（不含当前 user_msg）
    history_stmt = (
        select(Message)
        .where(Message.conversation_id == conv.id)
        .where(Message.id < user_msg.id)
        .order_by(Message.id)
        .limit(8)
    )
    history_result = await db.execute(history_stmt)
    history = [
        {"role": m.role, "content": m.content}
        for m in history_result.scalars()
    ]

    # 4. 意图识别 + query 改写（代词消解）+ 多问题检测
    intent_result = await recognize_intent(req.question, history)
    rewritten_query = intent_result["rewritten_query"]
    intent = intent_result["intent"]
    sub_questions = intent_result.get("sub_questions") or []

    logger.info(
        f"chat 改写: original={req.question[:50]!r}, "
        f"rewritten={rewritten_query[:50]!r}, intent={intent}, "
        f"sub_questions={len(sub_questions)}"
    )

    # 5. 检索 + 生成
    if sub_questions and len(sub_questions) > 1:
        # 多问题拆解：逐个子问题检索+生成，最后合并
        answer, results, trace = await _handle_multi_questions(
            sub_questions=sub_questions,
            history=history,
            top_k=req.top_k,
            db=db,
        )
    elif intent == STATS_INTENT:
        answer, results, trace = await _handle_stats_query(
            rewritten_query=rewritten_query,
            intent=intent,
            history=history,
            top_k=req.top_k,
            db=db,
        )
    else:
        # 整个 hybrid_search（含 embed + milvus 检索 + rerank）放线程池，
        # 避免 reranker 推理阻塞事件循环导致 /health 端点超时无响应
        results = await asyncio.to_thread(
            hybrid_search,
            rewritten_query,
            top_k=req.top_k,
            enable_rerank=req.enable_rerank,
            enable_wiki=req.enable_wiki,
        )

        if not results:
            answer = "未检索到相关资料，无法回答。"
            trace = {
                "retrieved": [],
                "wiki_used": False,
                "intent": intent,
                "rewritten_query": rewritten_query,
            }
        else:
            # 6. 拼 prompt（含 history + context + intent）
            prompt = build_rag_prompt(
                question=rewritten_query,
                context=results,
                history=history,
                intent=intent,
            )

            # 7. 调 DeepSeek 生成（显式传 main_model，不走 generate 默认 wiki_model）
            answer = await get_llm_client().generate(
                prompt, model=settings.deepseek_main_model
            )

            trace = {
                "retrieved": [
                    {
                        "doc_id": r.get("doc_id"),
                        "score": r.get("score"),
                        "retrieval_sources": r.get("retrieval_sources", []),
                    }
                    for r in results
                ],
                "wiki_used": any(
                    "wiki" in r.get("retrieval_sources", []) for r in results
                ),
                "intent": intent,
                "rewritten_query": rewritten_query,
            }

    # 8. 写 assistant message（含 trace）
    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=answer,
        trace=trace,
    )
    db.add(assistant_msg)
    # get_session 会自动 commit

    logger.info(
        f"chat 完成: conv_id={conv.id}, sources={len(results)}, "
        f"answer_len={len(answer)}"
    )

    # 9. 返回
    return ChatResponse(
        question=req.question,
        rewritten_query=rewritten_query,
        intent=intent,
        conversation_id=conv.id,
        answer=answer,
        sources=[
            ChatSource(
                text=r["text"][:500],
                score=r["score"],
                doc_id=r.get("doc_id"),
                category=r.get("category"),
                college=r.get("college"),
                subject=r.get("subject"),
                source_url=r.get("source_url"),
                retrieval_sources=r.get("retrieval_sources", []),
                rerank_score=r.get("rerank_score"),
                page_num=r.get("page_num"),
                char_start=r.get("char_start"),
                char_end=r.get("char_end"),
            )
            for r in results
        ],
    )


# ───── SSE 流式端点：分阶段推送思考过程 ─────


def _sse(event: str, data: dict) -> str:
    """构造 SSE 事件帧（event + data 两行 + 空行分隔）"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """RAG 问答流式：SSE 分阶段推送（意图→检索→rerank→生成逐 token）

    事件类型：
        intent_done   {intent, rewritten_query}      意图识别 + query 改写完成
        retrieving    {}                              开始检索
        retrieved     {sources_count}                 检索完成（含 rerank）
        generating    {}                              开始 LLM 生成
        token         {delta}                         生成的一个 token 片段
        done          {conversation_id, intent, ...}  全部完成（含完整 sources）
        error         {detail}                        异常
    """
    async def event_gen():
        # 各阶段累计耗时（从请求开始算），随每个 SSE 事件返回前端
        t0 = time.monotonic()

        def elapsed_ms() -> int:
            return int((time.monotonic() - t0) * 1000)

        try:
            # 1. 解析/创建 conversation
            if req.conversation_id:
                conv = await db.get(Conversation, req.conversation_id)
                if conv is None:
                    yield _sse("error", {"detail": "会话不存在"})
                    return
                if conv.user_id != user.id:
                    yield _sse("error", {"detail": "无权访问该会话"})
                    return
            else:
                conv = Conversation(user_id=user.id, title=req.question[:50])
                db.add(conv)
                await db.flush()

            # 2. 写 user message
            user_msg = Message(
                conversation_id=conv.id,
                role="user",
                content=req.question,
            )
            db.add(user_msg)
            await db.flush()

            # 3. 拉历史（不含当前 user_msg）
            history_stmt = (
                select(Message)
                .where(Message.conversation_id == conv.id)
                .where(Message.id < user_msg.id)
                .order_by(Message.id)
                .limit(8)
            )
            history_result = await db.execute(history_stmt)
            history = [
                {"role": m.role, "content": m.content}
                for m in history_result.scalars()
            ]

            # 4. 意图识别 + query 改写（代词消解）+ 多问题检测
            intent_result = await recognize_intent(req.question, history)
            rewritten_query = intent_result["rewritten_query"]
            intent = intent_result["intent"]
            sub_questions = intent_result.get("sub_questions") or []
            yield _sse("intent_done", {
                "intent": intent,
                "rewritten_query": rewritten_query,
                "sub_questions": sub_questions,
                "elapsed_ms": elapsed_ms(),
            })

            # 5. 检索或统计
            # 多问题拆解：降级为非流式处理
            if sub_questions and len(sub_questions) > 1:
                yield _sse("retrieving", {"elapsed_ms": elapsed_ms()})
                answer, results, trace = await _handle_multi_questions(
                    sub_questions=sub_questions,
                    history=history,
                    top_k=req.top_k,
                    db=db,
                )
                yield _sse("retrieved", {
                    "sources_count": len(results),
                    "elapsed_ms": elapsed_ms(),
                })
                yield _sse("generating", {"elapsed_ms": elapsed_ms()})
                yield _sse("token", {"delta": answer})
            elif intent == STATS_INTENT:
                yield _sse("retrieving", {"elapsed_ms": elapsed_ms()})
                answer, results, trace = await _handle_stats_query(
                    rewritten_query=rewritten_query,
                    intent=intent,
                    history=history,
                    top_k=req.top_k,
                    db=db,
                )
                yield _sse("retrieved", {
                    "sources_count": len(results),
                    "elapsed_ms": elapsed_ms(),
                })
                yield _sse("generating", {"elapsed_ms": elapsed_ms()})
                # 统计类用非流式生成，一次性推送完整 answer
                yield _sse("token", {"delta": answer})
            else:
                # 原流程：hybrid_search 检索 + 流式生成
                # 用 progress_callback + asyncio.Queue 把检索子阶段进度流式推送给前端
                yield _sse("retrieving", {"elapsed_ms": elapsed_ms()})

                loop = asyncio.get_running_loop()
                progress_queue: asyncio.Queue = asyncio.Queue()

                def progress_callback(stage: str):
                    """从子线程安全投递检索阶段进度到主事件循环"""
                    asyncio.run_coroutine_threadsafe(progress_queue.put(stage), loop)

                # 启动检索任务（并发运行，期间可继续 yield SSE 推送子阶段进度）
                search_task = asyncio.create_task(
                    asyncio.to_thread(
                        hybrid_search,
                        rewritten_query,
                        top_k=req.top_k,
                        enable_rerank=req.enable_rerank,
                        enable_wiki=req.enable_wiki,
                        progress_callback=progress_callback,
                    )
                )

                # 持续读取子阶段进度，推送 retrieving_stage 事件
                while not search_task.done():
                    get_task = asyncio.create_task(progress_queue.get())
                    done, _ = await asyncio.wait(
                        {search_task, get_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if get_task in done:
                        sub_stage = get_task.result()
                        yield _sse("retrieving_stage", {
                            "stage": sub_stage,
                            "elapsed_ms": elapsed_ms(),
                        })
                    else:
                        get_task.cancel()

                # 排空 queue 剩余进度（search_task 完成后可能还有未读的回调）
                while not progress_queue.empty():
                    sub_stage = progress_queue.get_nowait()
                    yield _sse("retrieving_stage", {
                        "stage": sub_stage,
                        "elapsed_ms": elapsed_ms(),
                    })

                results = await search_task
                yield _sse("retrieved", {
                    "sources_count": len(results),
                    "elapsed_ms": elapsed_ms(),
                })

                # 6. 拼 prompt + 流式生成
                if not results:
                    answer = "未检索到相关资料，无法回答。"
                    yield _sse("token", {"delta": answer})
                else:
                    prompt = build_rag_prompt(
                        question=rewritten_query,
                        context=results,
                        history=history,
                        intent=intent,
                    )
                    yield _sse("generating", {"elapsed_ms": elapsed_ms()})
                    answer_parts: list[str] = []
                    async for delta in get_llm_client().chat_stream(
                        [{"role": "user", "content": prompt}],
                        model=settings.deepseek_main_model,
                    ):
                        answer_parts.append(delta)
                        yield _sse("token", {"delta": delta})
                    answer = "".join(answer_parts)

            # 7. 写 assistant message（含 trace）
            # 统计类的 trace 已由 _handle_stats_query 返回，非统计类在此构建
            if intent != STATS_INTENT:
                trace = {
                    "retrieved": [
                        {
                            "doc_id": r.get("doc_id"),
                            "score": r.get("score"),
                            "retrieval_sources": r.get("retrieval_sources", []),
                        }
                        for r in results
                    ],
                    "wiki_used": any(
                        "wiki" in r.get("retrieval_sources", []) for r in results
                    ),
                    "intent": intent,
                    "rewritten_query": rewritten_query,
                }
            assistant_msg = Message(
                conversation_id=conv.id,
                role="assistant",
                content=answer,
                trace=trace,
            )
            db.add(assistant_msg)

            logger.info(
                f"chat_stream 完成: conv_id={conv.id}, sources={len(results)}, "
                f"answer_len={len(answer)}"
            )

            # 8. done（含完整 sources 供前端展示）
            yield _sse("done", {
                "elapsed_ms": elapsed_ms(),
                "conversation_id": conv.id,
                "intent": intent,
                "rewritten_query": rewritten_query,
                "answer": answer,
                "trace": trace,
                "sources": [
                    {
                        "text": r["text"][:500],
                        "score": r["score"],
                        "doc_id": r.get("doc_id"),
                        "category": r.get("category"),
                        "college": r.get("college"),
                        "subject": r.get("subject"),
                        "source_url": r.get("source_url"),
                        "retrieval_sources": r.get("retrieval_sources", []),
                        "rerank_score": r.get("rerank_score"),
                        "page_num": r.get("page_num"),
                        "char_start": r.get("char_start"),
                        "char_end": r.get("char_end"),
                    }
                    for r in results
                ],
            })
        except Exception as e:
            logger.exception(f"chat_stream 异常: {e}")
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
