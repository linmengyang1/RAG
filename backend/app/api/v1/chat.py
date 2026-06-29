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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import logger
from app.db.session import get_session
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.services.llm.deepseek_client import get_llm_client
from app.services.llm.intent_recognition import recognize_intent
from app.services.llm.prompt_builder import build_rag_prompt
from app.services.retrieval.hybrid_search import hybrid_search

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, description="用户问题")
    top_k: int = Field(5, ge=1, le=20, description="检索 chunk 数量")
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

    # 4. 意图识别 + query 改写（代词消解）
    intent_result = await recognize_intent(req.question, history)
    rewritten_query = intent_result["rewritten_query"]
    intent = intent_result["intent"]

    logger.info(
        f"chat 改写: original={req.question[:50]!r}, "
        f"rewritten={rewritten_query[:50]!r}, intent={intent}"
    )

    # 5. 检索相关 chunk（用改写后的 query）
    results = hybrid_search(
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
