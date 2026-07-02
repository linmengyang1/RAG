"""RAG prompt 构建器：含 history slot + intent 提示

保留原 chat.py 的 PROMPT_TEMPLATE 风格，扩展为支持：
- 多轮对话历史（最近 4 轮）
- 意图提示（让 LLM 知道用户意图）
- 上下文标记（每个 chunk 编号）
- 统计类 prompt（全量 wiki 条目列表）

用法：
    from app.services.llm.prompt_builder import build_rag_prompt
    prompt = build_rag_prompt(question, context, history, intent)

    # 统计类
    from app.services.llm.prompt_builder import build_stats_prompt
    prompt = build_stats_prompt(question, wiki_entries, history, intent)
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

    # 根据意图和问题长度推断复杂度，给出输出长度建议
    length_hint = _get_length_hint(question, intent)

    return f"""你是一个研究生院知识库助手。请基于以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实说明，不要编造。
回答时请引用资料来源（如"根据导师信息..."）。

历史对话：
{history_block or "（无）"}

参考资料：
{context_block}

用户问题：{question} {intent_hint}

{length_hint}
回答："""


def _get_length_hint(question: str, intent: str | None) -> str:
    """根据问题复杂度给出输出长度建议

    简单问题（如查单个导师信息）→ 建议 200 字以内
    中等问题（如问某个政策）→ 建议 500 字以内
    复杂问题（如统计/多问题/比较）→ 不做限制
    """
    q_len = len(question)

    # 统计类问题通常需要较长回答
    if intent == "统计查询":
        return "请根据数据给出完整统计，用列表或表格呈现。"

    # 简单查询：问题短且意图单一
    if q_len < 30 and intent in ("导师查询", "招生信息", "学位管理", "奖学金"):
        return "请简洁回答，控制在 200 字以内。"

    # 中等查询
    if q_len < 100:
        return "请简明扼要回答，控制在 500 字以内。"

    # 复杂问题不做限制
    return ""


# 统计类 prompt 每条条目 content_md 的最大字符数（控制总上下文长度）
STATS_ENTRY_MAX_CHARS = 120
# 统计类 prompt 总字数上限（超过则降级为只取 summary）
STATS_TOTAL_MAX_CHARS = 60000


def build_stats_prompt(
    question: str,
    wiki_entries: list[dict],
    history: Optional[list[dict]] = None,
    intent: Optional[str] = None,
) -> str:
    """构造统计类 prompt（全量 wiki 条目列表）

    与 build_rag_prompt 的区别：
    - build_rag_prompt 把 top_k 检索结果作为上下文，适合具体查询
    - build_stats_prompt 把全量 wiki 条目列表作为上下文，适合统计/聚合

    上下文长度控制：
    - 每条 content_md 截断到 STATS_ENTRY_MAX_CHARS 字
    - 如果总字数超过 STATS_TOTAL_MAX_CHARS，降级为只取 content_summary

    Args:
        question: 用户问题（已改写，无代词）
        wiki_entries: wiki 条目列表，每个 dict 含 title/content_md/content_summary
        history: 历史消息
        intent: 意图标签

    Returns:
        完整 prompt 字符串
    """
    # 历史对话块
    history_block = ""
    if history:
        lines = []
        for m in history[-8:]:
            role_zh = "用户" if m.get("role") == "user" else "助手"
            content = m.get("content", "")[:300]
            lines.append(f"{role_zh}: {content}")
        history_block = "\n".join(lines)

    # 构建条目列表，先用 content_md 截断版
    entries_parts: list[str] = []
    total_chars = 0
    use_summary_only = False
    for i, e in enumerate(wiki_entries, 1):
        title = e.get("title", "")
        content_md = e.get("content_md", "")
        summary = e.get("content_summary", "")
        line = f"[{i}] {title}：{content_md[:STATS_ENTRY_MAX_CHARS]}"
        total_chars += len(line)
        if total_chars > STATS_TOTAL_MAX_CHARS:
            # 超限，降级为只用 summary 重新构建
            use_summary_only = True
            break
        entries_parts.append(line)

    if use_summary_only:
        entries_parts = []
        for i, e in enumerate(wiki_entries, 1):
            title = e.get("title", "")
            summary = e.get("content_summary", "")
            line = f"[{i}] {title}：{summary}"
            entries_parts.append(line)

    entries_block = "\n".join(entries_parts)
    intent_hint = f"（用户意图：{intent}）" if intent else ""

    return f"""你是一个研究生院知识库助手。以下是知识库中所有导师条目的完整列表。请基于这些条目回答用户的统计问题。

历史对话：
{history_block or "（无）"}

导师条目列表（共 {len(wiki_entries)} 条）：
{entries_block}

用户问题：{question} {intent_hint}

要求：
1. 严格基于以上条目列表统计，不要编造未列出的导师
2. 给出总数、按学院分组、按职称分组等用户要求的统计维度
3. 如果条目信息不足以判断某个维度（如学院名缺失），如实说明
4. 统计结果用清晰的列表或表格呈现

回答："""


def build_stats_aggregate_prompt(
    question: str,
    aggregates: dict,
    history: Optional[list[dict]] = None,
    intent: Optional[str] = None,
) -> str:
    """构造统计类 prompt（基于 SQL 聚合结果，让 LLM 润色而非数数）

    与 build_stats_prompt 的区别：
    - build_stats_prompt 把全量导师条目列表喂给 LLM 让它数数（伪统计，易幻觉）
    - build_stats_aggregate_prompt 把已聚合好的统计数字喂给 LLM 让它润色输出（真统计）

    aggregates 结构：
        {
            "total": int,                              # 导师总数（去重）
            "by_college": [{"key": str, "count": int}, ...],  # 按学院分组
            "by_title": [{"key": str, "count": int}, ...],    # 按职称分组
            "by_subject": [{"key": str, "count": int}, ...],  # 按学科方向分组
        }

    Args:
        question: 用户问题（已改写，无代词）
        aggregates: SQL 聚合结果，结构如上
        history: 历史消息
        intent: 意图标签

    Returns:
        完整 prompt 字符串
    """
    # 历史对话块
    history_block = ""
    if history:
        lines = []
        for m in history[-8:]:
            role_zh = "用户" if m.get("role") == "user" else "助手"
            content = m.get("content", "")[:300]
            lines.append(f"{role_zh}: {content}")
        history_block = "\n".join(lines)

    # 构建聚合统计块
    total = aggregates.get("total", 0)

    def _format_groups(groups: list[dict], label: str) -> str:
        """格式化分组统计为文本块"""
        if not groups:
            return f"{label}：暂无数据"
        parts = []
        for g in groups:
            key = g.get("key") or "（未填写）"
            count = g.get("count", 0)
            parts.append(f"  - {key}：{count} 人")
        return f"{label}（共 {len(groups)} 项）：\n" + "\n".join(parts)

    college_block = _format_groups(aggregates.get("by_college", []), "按学院分组")
    title_block = _format_groups(aggregates.get("by_title", []), "按职称分组")
    subject_block = _format_groups(aggregates.get("by_subject", []), "按学科方向分组")

    intent_hint = f"（用户意图：{intent}）" if intent else ""

    return f"""你是一个研究生院知识库助手。以下是知识库中导师数据的统计结果（已由数据库聚合计算完成，无需你再数数）。请基于这些统计结果回答用户的统计问题。

历史对话：
{history_block or "（无）"}

导师统计结果（数据库聚合查询）：

导师总数：{total} 人

{college_block}

{title_block}

{subject_block}

用户问题：{question} {intent_hint}

要求：
1. 严格基于以上统计结果回答，不要编造未列出的数字
2. 数字已由数据库聚合计算，你只需组织语言呈现，不要重新数数
3. 根据用户问题选择相关维度作答（如问"各学院导师数"则只列学院分组）
4. 统计结果用清晰的列表或表格呈现
5. 如果统计结果不足以回答某个维度（如某字段为空），如实说明

回答："""
