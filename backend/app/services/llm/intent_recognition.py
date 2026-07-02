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

# 意图识别 prompt 模板（含 few-shot 示例）
INTENT_PROMPT = """你是一个意图识别器。基于用户的历史对话和当前问题，做四件事：
1. 判断当前问题是否包含多个独立子问题（如"X导师的研究方向是什么？他发了多少SCI论文？"）
2. 如果包含多个子问题，将其拆分为独立的子问题列表；如果只有一个问题，sub_questions 为空数组
3. 消解当前问题中的代词（他/她/它/这个/那个），改写成独立完整的问题
4. 判断意图标签并给出置信度（confidence: 0.0~1.0，表示你对意图判断的把握程度）

意图标签（8 类）：
- 导师查询：查询单个或少数具体导师的信息
- 统计查询：需要对大量数据做汇总、计数、分组统计
- 政策咨询：询问规定、制度、管理办法、文件内容
- 流程办理：询问办事步骤、所需材料、办理方式
- 招生信息：询问报考条件、考试科目、录取规则、调剂
- 学位管理：询问论文答辩、学位申请、毕业要求
- 奖学金：询问奖助学金、助研津贴、助学贷款
- 其他：以上都不匹配时使用

Few-shot 示例：

Q: 王鹏杰的研究方向是什么
A: {{"rewritten_query": "王鹏杰的研究方向是什么", "intent": "导师查询", "sub_questions": [], "is_multi_turn": false, "confidence": 0.98}}

Q: 数学学院有哪些导师？各学院导师数量统计
A: {{"rewritten_query": "数学学院有哪些导师？各学院导师数量统计", "intent": "统计查询", "sub_questions": ["数学学院有哪些导师", "各学院导师数量统计"], "is_multi_turn": false, "confidence": 0.96}}

Q: 研究生论文答辩流程是什么
A: {{"rewritten_query": "研究生论文答辩流程是什么", "intent": "流程办理", "sub_questions": [], "is_multi_turn": false, "confidence": 0.95}}

Q: 申请国家奖学金需要什么条件
A: {{"rewritten_query": "申请国家奖学金需要什么条件", "intent": "奖学金", "sub_questions": [], "is_multi_turn": false, "confidence": 0.93}}

Q: 2026年研究生招生的考试科目有哪些
A: {{"rewritten_query": "2026年研究生招生的考试科目有哪些", "intent": "招生信息", "sub_questions": [], "is_multi_turn": false, "confidence": 0.94}}

Q: 学位授予的毕业要求是什么
A: {{"rewritten_query": "学位授予的毕业要求是什么", "intent": "学位管理", "sub_questions": [], "is_multi_turn": false, "confidence": 0.92}}

Q: 研究生学籍管理规定
A: {{"rewritten_query": "研究生学籍管理规定", "intent": "政策咨询", "sub_questions": [], "is_multi_turn": false, "confidence": 0.91}}

Q: 你好
A: {{"rewritten_query": "你好", "intent": "其他", "sub_questions": [], "is_multi_turn": false, "confidence": 0.99}}

历史对话：
{history}

当前问题：{question}

请仅输出严格 JSON（无其他文字、无 markdown 代码块）：
{{"rewritten_query": "改写后的问题", "intent": "意图标签", "sub_questions": [], "is_multi_turn": true或false, "confidence": 0.0~1.0}}

注意：
- sub_questions 是字符串数组，每个元素是一个独立的子问题。如果用户问题包含多个独立问题则拆分，否则为空数组[]
- 拆分后的每个子问题都应该是独立可回答的完整问题
- 如果当前问题中没有代词或可独立理解，rewritten_query 与原问题相同
- is_multi_turn 为 true 当且仅当需要参考历史对话才能理解当前问题
- confidence 表示你对意图判断的置信度：0.9+ 表示非常确定，0.7-0.9 表示基本确定，0.5-0.7 表示不太确定
"""

# 置信度阈值：低于此值的意图判断被视为不可靠，回退到"其他"
INTENT_CONFIDENCE_THRESHOLD = 0.5

# 多问题合并 prompt 模板
COMBINE_ANSWERS_PROMPT = """你是一个研究生院知识库助手。用户提出了多个子问题，以下是每个子问题的独立回答。

请将这些回答整合成一个连贯的回复，使用清晰的标题和分段来组织不同问题的答案。

{answers_block}

要求：
1. 保持每个子问题答案的完整性，不要删减重要信息
2. 用清晰的标题区分不同问题的答案
3. 如果有子问题答案之间可以关联，可以在最后做简短总结

整合回答："""


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
    """解析 LLM 输出，提取置信度，低于阈值时回退到 '其他'"""
    if not resp:
        return {
            "rewritten_query": fallback_query, "intent": "其他",
            "sub_questions": [], "is_multi_turn": has_history, "confidence": 0.0,
        }

    text = resp.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        intent = str(data.get("intent") or "其他")
        confidence = float(data.get("confidence", 0.5))

        # 置信度低于阈值，回退到"其他"
        if confidence < INTENT_CONFIDENCE_THRESHOLD:
            logger.info(f"意图置信度过低 ({confidence:.2f} < {INTENT_CONFIDENCE_THRESHOLD})，回退到 '其他'")
            intent = "其他"

        return {
            "rewritten_query": str(data.get("rewritten_query") or fallback_query),
            "intent": intent,
            "sub_questions": list(data.get("sub_questions") or []),
            "is_multi_turn": bool(data.get("is_multi_turn", has_history)),
            "confidence": confidence,
        }
    except Exception as e:
        logger.warning(f"意图识别 JSON 解析失败: {e}, resp={resp[:200]!r}")
        return {
            "rewritten_query": fallback_query,
            "intent": "其他",
            "sub_questions": [],
            "is_multi_turn": has_history,
            "confidence": 0.0,
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
            f"confidence={result.get('confidence', 0):.2f}, "
            f"rewritten={result['rewritten_query'][:50]!r}, "
            f"multi_turn={result['is_multi_turn']}"
        )
        return result
    except Exception as e:
        logger.error(f"意图识别失败: {e}", exc_info=True)
        return {
            "rewritten_query": query,
            "intent": "其他",
            "sub_questions": [],
            "is_multi_turn": has_history,
            "confidence": 0.0,
        }
