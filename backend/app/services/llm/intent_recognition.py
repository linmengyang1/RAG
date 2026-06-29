"""意图识别 + query 改写（代词消解、多轮上下文）

流程：
    1. 接收原始 query + 历史对话
    2. 调用 LLM（deepseek_main_model）做意图识别
    3. 消解代词（他/她/它/这个/那个），改写成独立完整的问题
    4. 返回 {rewritten_query, intent, is_multi_turn}

LLM 输出 JSON，解析失败时兜底返回原 query（不阻断主流程）。
"""
from __future__ import annotations

import json
import re

from app.core.config import settings
from app.core.logging import logger
from app.services.llm.deepseek_client import get_llm_client

# 意图识别 prompt 模板
INTENT_PROMPT = """你是一个意图识别器。基于用户的历史对话和当前问题，做两件事：
1. 消解当前问题中的代词（他/她/它/这个/那个/那个东西），改写成独立完整的问题
2. 判断意图标签（从以下选一：导师查询、政策咨询、流程办理、招生信息、学位管理、奖学金、其他）

历史对话：
{history}

当前问题：{question}

请仅输出严格 JSON（无其他文字、无 markdown 代码块）：
{{"rewritten_query": "改写后的问题", "intent": "意图标签", "is_multi_turn": true或false}}

注意：
- 如果当前问题中没有代词或可独立理解，rewritten_query 与原问题相同
- is_multi_turn 为 true 当且仅当需要参考历史对话才能理解当前问题
"""


def _build_history_text(history: list[dict] | None) -> str:
    """把历史消息列表格式化为文本"""
    if not history:
        return "（无）"
    lines = []
    # 取最近 4 轮（8 条消息）
    for m in history[-8:]:
        role_zh = "用户" if m.get("role") == "user" else "助手"
        content = m.get("content", "")[:200]  # 截断避免过长
        lines.append(f"{role_zh}: {content}")
    return "\n".join(lines)


def _parse_intent_response(resp: str, fallback_query: str, has_history: bool) -> dict:
    """解析 LLM 输出，失败时兜底"""
    if not resp:
        return {"rewritten_query": fallback_query, "intent": "其他", "is_multi_turn": has_history}

    text = resp.strip()
    # 去除可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        return {
            "rewritten_query": str(data.get("rewritten_query") or fallback_query),
            "intent": str(data.get("intent") or "其他"),
            "is_multi_turn": bool(data.get("is_multi_turn", has_history)),
        }
    except Exception as e:
        logger.warning(f"意图识别 JSON 解析失败: {e}, resp={resp[:200]!r}")
        # 兜底：原样返回
        return {
            "rewritten_query": fallback_query,
            "intent": "其他",
            "is_multi_turn": has_history,
        }


async def recognize_intent(
    query: str, history: list[dict] | None = None
) -> dict:
    """识别意图 + 改写 query（消解代词）

    Args:
        query: 用户原始问题
        history: 历史消息列表 [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        {
            "rewritten_query": str,  # 改写后的 query（无代词）
            "intent": str,           # 意图标签
            "is_multi_turn": bool,   # 是否需要多轮上下文
        }
    """
    has_history = bool(history)
    history_text = _build_history_text(history)

    prompt = INTENT_PROMPT.format(history=history_text, question=query)
    logger.info(f"意图识别开始: query={query[:50]!r}, has_history={has_history}")

    try:
        # 显式用 main_model（v4-flash），不用 wiki_model
        resp = await get_llm_client().generate(
            prompt, model=settings.deepseek_main_model
        )
        result = _parse_intent_response(resp, query, has_history)
        logger.info(
            f"意图识别完成: intent={result['intent']}, "
            f"rewritten={result['rewritten_query'][:50]!r}, "
            f"multi_turn={result['is_multi_turn']}"
        )
        return result
    except Exception as e:
        logger.error(f"意图识别失败: {e}", exc_info=True)
        return {
            "rewritten_query": query,
            "intent": "其他",
            "is_multi_turn": has_history,
        }
