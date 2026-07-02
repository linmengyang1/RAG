"""导师实体构建器：从 wiki person 条目 + 文件名匹配反推 mentors 表

工作流程（两步）：
1. build_mentors_from_wiki()：遍历 wiki person 条目 → 按 name 合并 → 写 Mentor + MentorIdentity
2. link_chunks_to_mentor()：遍历 category='导师信息' 的文档 → 按文件名解析导师姓名
   → 匹配 Mentor.name → 回填 chunks.mentor_id

边界处理：
- 同名导师（birth_year 解析不到时）做合并，取第一个作为主 Mentor，
  其余作为 MentorIdentity 附加
- chunks 历史回填匹配率不会 100%，未匹配 chunk 保持 mentor_id=NULL
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select, update

from app.core.logging import logger
from app.db.session import session_scope
from app.models.document import Chunk, Document
from app.models.mentor import Mentor, MentorIdentity
from app.models.wiki import WikiEntry


def _parse_name_from_filename(file_path: str) -> str | None:
    """从文件路径中解析导师姓名

    文件路径示例：
        导师信息/机电工程学院/机械类别/王阳_机电工程学院_机械类别.md
        导师信息/计算机科学与工程学院/人工智能/薛明亮_计算机科学与工程学院_人工智能.md
        导师信息/马克思主义学院/陈宪章_马克思主义学院.md
        导师信息/国际商学院/云健_国际商学院.pdf

    返回第一个下划线前的内容作为姓名。
    """
    filename = Path(file_path).name
    # 去掉后缀
    filename = re.sub(r"\.(md|pdf|docx|doc)$", "", filename, flags=re.IGNORECASE)
    # 取第一个下划线前的内容作为姓名
    parts = filename.split("_", 1)
    name = parts[0].strip() if parts else filename.strip()
    if not name or len(name) < 2:
        return None
    return name


def _parse_identity_from_file_path(file_path: str) -> dict:
    """从文件路径中解析导师身份信息

    文件路径模式：
        导师信息/{学院}/{学科方向}/{姓名}_{学院}_{学科方向}.md
        导师信息/{学院}/{姓名}_{学院}.md
        导师信息/{姓名}_{学院}.pdf

    返回 {"college": str, "subject": str | None}
    """
    parts = Path(file_path).parts
    college = ""
    subject = None

    # 导师信息 目录下的路径模式
    for p in parts:
        if p == "导师信息":
            continue
        if not college and p not in ("", "导师信息"):
            college = p
            continue
        if college and p != Path(file_path).name and p not in ("", "导师信息"):
            subject = p
            break

    # 也可能从文件名中提取
    if not college:
        filename = Path(file_path).stem
        segs = filename.split("_")
        if len(segs) >= 3:
            college = segs[1]
            subject = segs[2]

    return {"college": college, "subject": subject}


async def build_mentors_from_wiki() -> dict:
    """从 wiki person 条目反推导师实体

    遍历所有 entry_type='person' 的 wiki 条目，按 name 合并同名导师，
    写入 Mentor 表 + 回填 wiki_entry_id，同时为每个 person 条目创建
    对应的 MentorIdentity。

    Returns:
        {"mentors": int, "identities": int, "merged": int}
    """
    logger.info("开始从 wiki person 条目构建 Mentor 实体...")

    # 1. 读取所有 person 类型 wiki 条目
    async with session_scope() as session:
        stmt = select(WikiEntry).where(WikiEntry.entry_type == "person")
        result = await session.execute(stmt)
        person_entries = result.scalars().all()

    if not person_entries:
        logger.warning("没有 person 类型的 wiki 条目，跳过 Mentor 构建")
        return {"mentors": 0, "identities": 0, "merged": 0}

    logger.info(f"读取到 {len(person_entries)} 条 person 类型的 wiki 条目")

    # 2. 按 name 分组，同时尝试从 content_md 解析 birth_year
    name_groups: dict[str, list[WikiEntry]] = defaultdict(list)
    for entry in person_entries:
        name = entry.title.strip()
        if name:
            name_groups[name].append(entry)

    # 3. 为每组创建 Mentor + MentorIdentity
    mentor_count = 0
    identity_count = 0
    merged_count = 0  # 同名合并次数

    async with session_scope() as session:
        for name, entries in name_groups.items():
            # 取第一个条目作为主 Mentor
            first = entries[0]
            primary_college = first.college or ""

            # 尝试从 content_md 解析 birth_year
            birth_year = _extract_birth_year(first.content_md or "")

            mentor = Mentor(
                name=name,
                primary_college=primary_college,
                wiki_entry_id=first.id,
                birth_year=birth_year,
            )
            session.add(mentor)
            await session.flush()
            mentor_count += 1

            if len(entries) > 1:
                merged_count += len(entries) - 1

            # 4. 为每个 person 条目创建 MentorIdentity
            for entry in entries:
                identity = MentorIdentity(
                    mentor_id=mentor.id,
                    college=entry.college or "",
                    subject_direction=entry.subject or "",
                    title=_extract_title(entry.content_md or ""),
                    source_doc_id=(
                        entry.source_doc_ids[0]
                        if entry.source_doc_ids and len(entry.source_doc_ids) > 0
                        else None
                    ),
                )
                session.add(identity)
                identity_count += 1

    logger.info(
        f"Mentor 构建完成: mentors={mentor_count}, "
        f"identities={identity_count}, merged={merged_count}"
    )
    return {
        "mentors": mentor_count,
        "identities": identity_count,
        "merged": merged_count,
    }


async def link_chunks_to_mentor() -> dict:
    """将 category='导师信息' 的文档的 chunks 关联到对应的 mentor

    按文档文件名解析导师姓名 → 匹配 Mentor.name → 回填 chunks.mentor_id。
    未匹配的 chunk 保持 mentor_id=NULL（不影响检索）。

    Returns:
        {"total_chunks": int, "linked": int, "unmatched_docs": int}
    """
    logger.info("开始将 chunks 关联到 Mentor...")

    # 1. 查询所有 Mentor（建立 name → id 映射）
    async with session_scope() as session:
        stmt = select(Mentor.id, Mentor.name)
        result = await session.execute(stmt)
        mentor_map: dict[str, int] = {}
        for mid, mname in result:
            if mname:
                mentor_map[mname.strip()] = mid

    if not mentor_map:
        logger.warning("mentors 表为空，跳过 chunk 关联")
        return {"total_chunks": 0, "linked": 0, "unmatched_docs": 0}

    logger.info(f"已加载 {len(mentor_map)} 个 Mentor 记录")

    # 2. 查询所有 category='导师信息' 的 documents
    async with session_scope() as session:
        stmt = select(Document.id, Document.file_path).where(
            Document.category == "导师信息"
        )
        result = await session.execute(stmt)
        docs = [(doc_id, file_path) for doc_id, file_path in result]

    if not docs:
        logger.warning("没有 category='导师信息' 的文档，跳过 chunk 关联")
        return {"total_chunks": 0, "linked": 0, "unmatched_docs": 0}

    # 3. 建立 doc_id → mentor_id 映射
    doc_mentor_map: dict[int, int] = {}
    unmatched_docs = 0
    for doc_id, file_path in docs:
        name = _parse_name_from_filename(file_path)
        if name and name in mentor_map:
            doc_mentor_map[doc_id] = mentor_map[name]
        else:
            unmatched_docs += 1
            logger.debug(f"  未匹配: {file_path} → name={name}")

    logger.info(
        f"文档-导师匹配: {len(doc_mentor_map)}/{len(docs)} 匹配成功, "
        f"{unmatched_docs} 未匹配"
    )

    # 4. 回填 chunks.mentor_id
    total_linked = 0
    async with session_scope() as session:
        for doc_id, mentor_id in doc_mentor_map.items():
            stmt = (
                update(Chunk)
                .where(Chunk.document_id == doc_id)
                .where(Chunk.mentor_id.is_(None))
                .values(mentor_id=mentor_id)
            )
            result = await session.execute(stmt)
            linked = result.rowcount or 0
            total_linked += linked

    logger.info(f"chunks 关联完成: {total_linked} 个 chunk 已关联")

    return {
        "total_chunks": total_linked,
        "linked": total_linked,
        "unmatched_docs": unmatched_docs,
    }


def _extract_birth_year(content_md: str) -> int | None:
    """从 content_md 中提取出生年份"""
    # 常见模式：出生年份 1965 / 1965年 / (1965-
    patterns = [
        r"(\d{4})\s*年\s*出生",
        r"出生\s*年份\s*[：:]\s*(\d{4})",
        r"出生年月[：:]\s*(\d{4})",
        r"\((\d{4})\s*[-–—]\s*\)",  # (1965 - )
        r"(\d{4})\s*年",
    ]
    for pattern in patterns:
        match = re.search(pattern, content_md)
        if match:
            year = int(match.group(1))
            if 1920 <= year <= 2000:  # 合理的出生年份范围
                return year
    return None


def _extract_title(content_md: str) -> str | None:
    """从 content_md 中提取职称"""
    title_patterns = [
        r"职称[：:]\s*([^\n，。,\.]{2,20})",
        r"教授|副教授|讲师|研究员|副研究员|高级工程师|工程师",
    ]
    # 先尝试精确匹配
    match = re.search(title_patterns[0], content_md)
    if match:
        return match.group(1).strip()
    # 再尝试模糊匹配
    match = re.search(title_patterns[1], content_md)
    if match:
        return match.group(0).strip()
    return None
