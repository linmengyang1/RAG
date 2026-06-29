"""RAG prompt 构建器：含 history slot + intent 提示

保留原 chat.py 的 PROMPT_TEMPLATE 风格，扩展为支持：
- 多轮对话历史（最近 4 轮）
- 意图提示（让 LLM 知道用户意图）
- 上下文标记（每个 chunk 编号）

用法：
    from app.services.llm.prompt_builder import build_rag_prompt
    prompt = build_rag_prompt(question, context, history, intent)
"""
from __future__ import annotations

from typing import Optional


def build_rag_prompt(
    question: str,
    context: list[dict],
    history: Optional[list[dict]] = None,
    intent: Optional[str] = None,
) -> str:
    """构造 RAG prompt

    Args:
        question: 用户问题（已改写，无代词）
        context: 检索结果列表，每个 dict 至少含 "text" 字段
        history: 历史消息 [{"role": "user"/"assistant", "content": "..."}]
        intent: 意图标签（如 "导师查询"）

    Returns:
        完整 prompt 字符串
    """
    # 历史对话块（取最近 4 轮，即 8 条消息）
    history_block = ""
    if history:
        lines = []
        for m in history[-8:]:
            role_zh = "用户" if m.get("role") == "user" else "助手"
            content = m.get("content", "")[:300]  # 截断避免过长
            lines.append(f"{role_zh}: {content}")
        history_block = "\n".join(lines)

    # 上下文块（每个 chunk 编号）
    context_parts = []
    for i, c in enumerate(context, 1):
        text = c.get("text", "")
        context_parts.append(f"[{i}] {text}")
    context_block = "\n\n".join(context_parts)

    # 意图提示
    intent_hint = f"（用户意图：{intent}）" if intent else ""

    return f"""你是一个研究生院知识库助手。请基于以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实说明，不要编造。
回答时请引用资料来源（如"根据导师信息..."）。

历史对话：
{history_block or "（无）"}

参考资料：
{context_block}

用户问题：{question} {intent_hint}

回答："""
