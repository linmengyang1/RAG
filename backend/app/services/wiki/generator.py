"""Wiki 条目生成器：从 chunks 提取人物/政策/流程条目，LLM 沉淀到 PG + Milvus

流程：
    1. 从 Milvus chunks 集合查 N 条 chunk（按 doc_id 过滤或全部）
    2. 每 10 个 chunk 一批，调 LLM（deepseek_wiki_model v4-pro）提取候选条目
    3. 去重（title 已存在则 skip）
    4. 计算 content_summary 的 dense 向量
    5. 写入 WikiEntry 表（PG）+ Milvus wiki 集合

用法：
    from app.services.wiki.generator import generate_wiki_entries
    stats = await generate_wiki_entries(doc_ids=[1,2,3], limit=50)
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import logger
from app.db.session import session_scope
from app.models.wiki import WikiEntry
from app.services.ingestion.embedder import embed
from app.services.ingestion.milvus_writer import get_client
from app.services.llm.deepseek_client import get_llm_client

# wiki 生成 prompt
WIKI_GEN_PROMPT = """你是研究生院知识库管理员。请从以下文本中提取可沉淀的实体条目。
仅提取以下三类：
- person（导师姓名、领导姓名，含简介、研究方向、联系方式等）
- policy（制度、规定、政策名称，含适用范围、要点等）
- process（流程、步骤名称，含步骤、所需材料、办理方式等）

只提取明确出现的实体，不要编造。

输出严格 JSON 数组（无其他文字、无 markdown 代码块）：
[{{"title": "实体名称（去重用，唯一）", "entry_type": "person|policy|process", "content_md": "条目内容（200 字以内，结构化）", "content_summary": "一句话摘要（50 字以内）"}}]

如果文本中没有可提取的实体，输出空数组 []。

文本：
{text}
"""

# 每批 chunk 数量
BATCH_SIZE = 10
# 每批文本最大字符数（避免超过 LLM 上下文）
MAX_BATCH_CHARS = 8000


def _parse_wiki_candidates(resp: str) -> list[dict]:
    """解析 LLM 输出为候选条目列表，失败时返回空"""
    if not resp:
        return []
    text = resp.strip()
    # 去除 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return []
        # 规范化字段
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            entry_type = str(item.get("entry_type", "")).strip()
            content_md = str(item.get("content_md", "")).strip()
            if not title or not entry_type or not content_md:
                continue
            if entry_type not in ("person", "policy", "process"):
                continue
            result.append({
                "title": title[:255],
                "entry_type": entry_type,
                "content_md": content_md,
                "content_summary": str(item.get("content_summary", ""))[:500] or title,
            })
        return result
    except Exception as e:
        logger.warning(f"wiki candidates JSON 解析失败: {e}, resp={resp[:200]!r}")
        return []


def _fetch_chunks_from_milvus(
    doc_ids: list[int] | None, limit: int
) -> list[dict]:
    """从 Milvus chunks 集合查 chunk 全文"""
    client = get_client()
    collection = settings.milvus_collection_chunks

    # 构造过滤表达式
    filter_expr = ""
    if doc_ids:
        # Milvus IN 表达式：doc_id in [1, 2, 3]
        filter_expr = f"doc_id in {doc_ids}"

    logger.info(
        f"查询 Milvus chunks: filter={filter_expr or '(无)'}, limit={limit}"
    )
    chunks = client.query(
        collection_name=collection,
        filter=filter_expr or None,
        output_fields=["text", "doc_id"],
        limit=limit,
    )
    logger.info(f"查询到 {len(chunks)} 个 chunk")
    return chunks


async def generate_wiki_entries(
    doc_ids: list[int] | None = None,
    limit: int = 50,
) -> dict:
    """从 chunks 提取 wiki 条目并写入 PG + Milvus

    Args:
        doc_ids: 限定从哪些 document 提取（None 表示全部）
        limit: 处理的 chunk 数量上限

    Returns:
        {"generated": int, "skipped": int, "errors": int}
    """
    logger.info(
        f"启动 wiki 生成: doc_ids={doc_ids}, limit={limit}"
    )

    # 1. 从 Milvus 查 chunks
    chunks = _fetch_chunks_from_milvus(doc_ids, limit)
    if not chunks:
        logger.warning("无 chunks 可提取 wiki，请先摄入数据")
        return {"generated": 0, "skipped": 0, "errors": 0}

    # 2. 批量调 LLM 提取候选条目
    all_candidates: list[dict] = []
    errors = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        batch_text = "\n\n---\n\n".join(c.get("text", "") for c in batch)
        # 截断避免超过 LLM 上下文
        batch_text = batch_text[:MAX_BATCH_CHARS]
        prompt = WIKI_GEN_PROMPT.format(text=batch_text)
        try:
            resp = await get_llm_client().generate(
                prompt, model=settings.deepseek_wiki_model  # wiki 用 v4-pro
            )
            candidates = _parse_wiki_candidates(resp)
            # 标注来源 doc_ids（去重）
            source_ids = list({c.get("doc_id") for c in batch if c.get("doc_id")})
            for cand in candidates:
                cand["source_doc_ids"] = source_ids
            all_candidates.extend(candidates)
            logger.info(
                f"wiki 批次 {i // BATCH_SIZE + 1}: 提取 {len(candidates)} 条候选"
            )
        except Exception as e:
            logger.error(f"wiki 批次 {i // BATCH_SIZE + 1} 失败: {e}", exc_info=True)
            errors += 1

    if not all_candidates:
        logger.warning("未提取到任何 wiki 候选条目")
        return {"generated": 0, "skipped": 0, "errors": errors}

    logger.info(f"共提取 {len(all_candidates)} 条候选，开始去重写入")

    # 3. 写入 PG + Milvus
    generated = 0
    skipped = 0
    async with session_scope() as session:
        # 查已存在的 title
        titles = [c["title"] for c in all_candidates]
        existing_titles = set()
        if titles:
            # 分批查避免 IN 列表过长
            for j in range(0, len(titles), 100):
                batch_titles = titles[j:j + 100]
                stmt = select(WikiEntry.title).where(WikiEntry.title.in_(batch_titles))
                result = await session.execute(stmt)
                existing_titles.update(row[0] for row in result)

        # 创建新条目
        new_entries: list[WikiEntry] = []
        for cand in all_candidates:
            if cand["title"] in existing_titles:
                skipped += 1
                continue
            entry = WikiEntry(
                title=cand["title"],
                entry_type=cand["entry_type"],
                content_md=cand["content_md"],
                content_summary=cand["content_summary"],
                source_doc_ids=cand.get("source_doc_ids", []),
            )
            session.add(entry)
            new_entries.append(entry)
            existing_titles.add(cand["title"])  # 同批次去重
            generated += 1

        await session.flush()

        # 4. 计算向量 + 写 Milvus
        if new_entries:
            texts = [e.content_summary or e.title for e in new_entries]
            embeddings = embed(texts)
            wiki_data = []
            for e, emb in zip(new_entries, embeddings):
                wiki_data.append({
                    "dense": emb.dense,
                    "title": e.title[:255],
                    "entry_type": e.entry_type[:32],
                    "content": e.content_md[:32768],
                    "summary": (e.content_summary or "")[:1024],
                })

            milvus_client = get_client()
            result = milvus_client.insert(
                collection_name=settings.milvus_collection_wiki,
                data=wiki_data,
            )
            ids = result.get("ids", []) if isinstance(result, dict) else []
            logger.info(f"wiki Milvus 写入: {len(ids)} 条, ids 示例={ids[:3]}")

    stats = {"generated": generated, "skipped": skipped, "errors": errors}
    logger.info(f"wiki 生成完成: {stats}")
    return stats
