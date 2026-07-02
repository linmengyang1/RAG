"""WikiLink 双向链接构建器（零 token 成本方案）

基于已有结构化数据（WikiEntry.college/subject/entry_type/source_doc_ids +
chunks.mentor_id + mentor.wiki_entry_id）构建 wiki_links 表，无需重跑 LLM。

链接类型（4 类，每条目每类最多 MAX_LINKS_PER_ENTRY 个，避免 N² 爆炸）：
1. 同学院导师互链：person + 同 college → relation="同学院"
2. 同方向导师互链：person + 同 subject → relation="同方向"
3. 同学院政策/流程互链：policy/process + 同 college → relation="同学院"
4. 文档来源导师互链：policy/process → source_doc_ids → chunks.mentor_id
   → mentor.wiki_entry_id → relation="相关导师"

双向插入：(A,B) 和 (B,A) 都写入表，UNIQUE(src,dst,relation) 保证幂等。
用 (min,max,relation) 规范化键去重，避免同一对重复收集。

用法：
    from app.services.wiki.link_builder import build_all_links
    stats = await build_all_links()
    # {"同学院导师": int, "同方向导师": int, "同学院政策流程": int,
    #  "相关导师": int, "collected_pairs": int, "inserted_rows": int}

    # 清空重建
    from app.services.wiki.link_builder import clear_all_links
    await clear_all_links()
    await build_all_links()
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import logger
from app.db.session import session_scope
from app.models.document import Chunk
from app.models.mentor import Mentor
from app.models.wiki import WikiEntry, WikiLink

# 每条目每类链接上限，避免同学院 50 导师全互链 = 2450 条爆炸
MAX_LINKS_PER_ENTRY = 10


def _collect_same_field_links(
    entries: list[WikiEntry],
    field: str,
    relation: str,
    links: set[tuple[int, int, str]],
) -> int:
    """按字段分组，收集两两互链对（规范化为 (min,max,relation) 去重）

    Args:
        entries: wiki 条目列表
        field: 分组字段名（"college" / "subject"）
        relation: 链接关系标签
        links: 累积的链接集合（会被修改）

    Returns:
        本次新增的链接对数（单向计数，双向插入时扩展为 (A,B) 和 (B,A)）
    """
    # 按 field 分组
    groups: dict[str, list[int]] = defaultdict(list)
    for e in entries:
        val = getattr(e, field, None)
        if val:
            groups[val].append(e.id)

    added = 0
    for val, ids in groups.items():
        if len(ids) < 2:
            continue
        # 对每个条目，链接同组的其他条目（按 id 升序取前 MAX 个，保证稳定）
        for i, src in enumerate(ids):
            others = sorted(x for j, x in enumerate(ids) if j != i)
            for dst in others[:MAX_LINKS_PER_ENTRY]:
                # 用 (min,max,relation) 规范化键，使 (A,B) 和 (B,A) 视为同一对
                pair = (min(src, dst), max(src, dst), relation)
                if pair not in links:
                    links.add(pair)
                    added += 1
    return added


async def _collect_doc_mentor_links(
    session, links: set[tuple[int, int, str]]
) -> int:
    """收集文档来源导师互链对

    对 policy/process wiki 条目，通过 source_doc_ids → chunks.mentor_id
    → mentor.wiki_entry_id 找到相关导师 person 条目，建立链接。
    relation="相关导师"
    """
    # 1. 查询 policy/process wiki 条目（有 source_doc_ids 的）
    pp_stmt = select(WikiEntry).where(
        WikiEntry.entry_type.in_(["policy", "process"]),
        WikiEntry.source_doc_ids.isnot(None),
    )
    pp_entries = (await session.execute(pp_stmt)).scalars().all()
    if not pp_entries:
        return 0

    # 2. 查询 mentor_id → wiki_entry_id 映射
    mentor_stmt = select(Mentor.id, Mentor.wiki_entry_id).where(
        Mentor.wiki_entry_id.isnot(None)
    )
    mentor_to_wiki: dict[int, int] = {
        mid: wid
        for mid, wid in (await session.execute(mentor_stmt))
        if wid is not None
    }

    # 3. 查询 document_id → mentor_id 映射（从 chunks 去重）
    chunk_stmt = (
        select(Chunk.document_id, Chunk.mentor_id)
        .where(Chunk.mentor_id.isnot(None))
        .distinct()
    )
    doc_to_mentor: dict[int, int] = {
        doc_id: mentor_id
        for doc_id, mentor_id in (await session.execute(chunk_stmt))
        if mentor_id is not None
    }

    # 4. 对每个 policy/process 条目，收集相关导师 wiki 条目
    added = 0
    for entry in pp_entries:
        if not entry.source_doc_ids:
            continue
        linked_wiki_ids: set[int] = set()
        for doc_id in entry.source_doc_ids:
            mentor_id = doc_to_mentor.get(doc_id)
            if mentor_id and mentor_id in mentor_to_wiki:
                linked_wiki_ids.add(mentor_to_wiki[mentor_id])
        # 按 id 升序取前 MAX 个，保证稳定
        for wiki_id in sorted(linked_wiki_ids)[:MAX_LINKS_PER_ENTRY]:
            pair = (min(entry.id, wiki_id), max(entry.id, wiki_id), "相关导师")
            if pair not in links:
                links.add(pair)
                added += 1
    return added


async def build_all_links() -> dict:
    """构建全部 wiki 双向链接（4 类，批量幂等插入）

    幂等：重复运行不报错（ON CONFLICT DO NOTHING 跳过已存在的链接）。

    Returns:
        {"同学院导师": int, "同方向导师": int, "同学院政策流程": int,
         "相关导师": int, "collected_pairs": int, "inserted_rows": int}
    """
    logger.info("开始构建 wiki 双向链接（零 token 成本方案）...")

    links: set[tuple[int, int, str]] = set()
    stats = {
        "同学院导师": 0,
        "同方向导师": 0,
        "同学院政策流程": 0,
        "相关导师": 0,
    }

    async with session_scope() as session:
        # 1. 同学院导师互链（person + 同 college）
        person_stmt = select(WikiEntry).where(
            WikiEntry.entry_type == "person",
            WikiEntry.college.isnot(None),
        )
        persons = (await session.execute(person_stmt)).scalars().all()
        stats["同学院导师"] = _collect_same_field_links(
            persons, "college", "同学院", links
        )

        # 2. 同方向导师互链（person + 同 subject）
        stats["同方向导师"] = _collect_same_field_links(
            persons, "subject", "同方向", links
        )

        # 3. 同学院政策/流程互链（policy/process + 同 college）
        pp_stmt = select(WikiEntry).where(
            WikiEntry.entry_type.in_(["policy", "process"]),
            WikiEntry.college.isnot(None),
        )
        pp_entries = (await session.execute(pp_stmt)).scalars().all()
        stats["同学院政策流程"] = _collect_same_field_links(
            pp_entries, "college", "同学院", links
        )

        # 4. 文档来源导师互链
        stats["相关导师"] = await _collect_doc_mentor_links(session, links)

        # 批量双向插入：每个 (A,B,rel) 同时写 (A→B) 和 (B→A)
        batch = []
        for a, b, rel in links:
            batch.append({"src_entry_id": a, "dst_entry_id": b, "relation": rel})
            batch.append({"src_entry_id": b, "dst_entry_id": a, "relation": rel})

        inserted = 0
        if batch:
            # 用 index_elements 而非 constraint 名，避免 init_postgres.sql
            # 未命名 UNIQUE 约束（PG 自动生成名）与 model 的 name 不一致
            stmt = (
                pg_insert(WikiLink)
                .values(batch)
                .on_conflict_do_nothing(
                    index_elements=["src_entry_id", "dst_entry_id", "relation"]
                )
            )
            result = await session.execute(stmt)
            inserted = result.rowcount or 0

    stats["collected_pairs"] = len(links)
    stats["inserted_rows"] = inserted
    logger.info(f"wiki 双向链接构建完成: {stats}")
    return stats


async def clear_all_links() -> int:
    """清空所有 wiki_links（重新构建前调用）

    Returns:
        删除的行数
    """
    async with session_scope() as session:
        result = await session.execute(delete(WikiLink))
        return result.rowcount or 0
