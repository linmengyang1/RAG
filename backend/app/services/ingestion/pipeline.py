"""端到端摄入管线：scanner -> parser -> chunker -> embedder -> milvus

流程（每个文件）：
    1. 扫描得到 ScanResult
    2. 写 Document 到 PG（status=pending）
    3. 解析：md 用 markdown_parser；pdf/docx 走 mineru_client
    4. 切片：chunker.chunk_text() -> list[TextChunk]
    5. 写 Chunk 到 PG（milvus_id 暂空）
    6. 向量化：embedder.embed() -> list[Embedding]
    7. 写 Milvus：milvus_writer.insert_chunks() -> milvus_ids
    8. 回写 chunk.milvus_id + document.status=embedded

异常时：document.status=failed + error_msg
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import logger
from app.db.session import session_scope
from app.models.document import (
    Chunk,
    Document,
    DOC_STATUS_EMBEDDED,
    DOC_STATUS_EMBEDDING,
    DOC_STATUS_FAILED,
    DOC_STATUS_PARSED,
    DOC_STATUS_PARSING,
    DOC_STATUS_PENDING,
)
from app.models.mentor import Mentor
from app.services.ingestion.chunker import chunk_text
from app.services.ingestion.embedder import embed
from app.services.ingestion.markdown_parser import ParsedDoc, parse_markdown
from app.services.ingestion.milvus_writer import get_client, insert_chunks
from app.services.ingestion.mineru_client import get_mineru_client
from app.services.ingestion.scanner import ScanResult, scan


async def _parse_file(sr: ScanResult) -> ParsedDoc:
    """解析文件，返回 ParsedDoc

    md 文件用 markdown_parser（同步，不走网络）；
    pdf/docx 走 MinerU API，解析后缓存 md 到 mineru_cache_dir，
    重跑时优先读缓存，避免重复消耗 MinerU 配额。
    """
    if sr.file_type == "md":
        parsed = parse_markdown(sr.path)
        # 路径推断的 college/subject 更可靠，覆盖 frontmatter 的值
        if sr.college:
            parsed.college = sr.college
        if sr.subject:
            parsed.subject = sr.subject
        return parsed

    # pdf/docx：先查 MinerU md 缓存
    cache_path = _mineru_cache_path(sr.rel_path)
    if cache_path.exists():
        logger.info(f"命中 MinerU 缓存: {cache_path}")
        return ParsedDoc(
            text=cache_path.read_text(encoding="utf-8"),
            college=sr.college,
            subject=sr.subject,
            page_map=None,  # 缓存 md 不含页码映射，但不影响切片
        )

    # 缓存未命中，走 MinerU API
    client = get_mineru_client()
    result = await client.parse(sr.path)

    # 保存 MinerU markdown 到本地缓存
    _save_mineru_cache(cache_path, result.markdown)

    return ParsedDoc(
        text=result.markdown,
        college=sr.college,
        subject=sr.subject,
        page_map=result.page_map,  # 可能为 None（MinerU 不一定提供页码映射）
    )


def _mineru_cache_path(rel_path: str) -> Path:
    """根据文件相对路径计算 MinerU 缓存文件路径

    files/培养工作/答辩公告/1173_xxx.pdf
        → /data/output/files_md/培养工作/答辩公告/1173_xxx.md
    """
    output_dir = Path(settings.data_output_dir)
    # rel_path 如 "files/培养工作/xxx.pdf"，去掉 "files/" 前缀后在 files_md/ 下重建结构
    if rel_path.startswith("files/"):
        rel_md = "files_md/" + rel_path[6:]
    else:
        rel_md = "files_md/" + rel_path
    return (output_dir / rel_md).with_suffix(".md")


def _save_mineru_cache(cache_path: Path, markdown: str) -> None:
    """保存 MinerU 解析结果为本地 md 缓存文件"""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(markdown, encoding="utf-8")
        logger.info(f"MinerU 缓存已保存: {cache_path}")
    except OSError as e:
        logger.warning(f"保存 MinerU 缓存失败: {e}")


async def _get_or_create_document(session, sr: ScanResult) -> tuple[int, bool]:
    """获取或创建 Document，返回 (doc_id, already_embedded)"""
    result = await session.execute(
        select(Document).where(Document.file_path == sr.rel_path)
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        doc = Document(
            file_path=sr.rel_path,
            file_type=sr.file_type,
            category=sr.category,
            college=sr.college,
            subject=sr.subject,
            doc_source=sr.doc_source,
            status=DOC_STATUS_PENDING,
        )
        session.add(doc)
        await session.flush()
        return doc.id, False

    if doc.status == DOC_STATUS_EMBEDDED:
        return doc.id, True

    # 重置状态（之前失败过，重新摄入）
    doc.status = DOC_STATUS_PENDING
    doc.error_msg = None
    await session.flush()
    return doc.id, False


async def _update_doc_status(doc_id: int, status: str, error_msg: Optional[str] = None) -> None:
    """更新 Document 状态"""
    async with session_scope() as session:
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = status
            if error_msg is not None:
                doc.error_msg = error_msg[:500]


async def run_pipeline(
    limit_md: Optional[int] = None,
    limit_pdf: Optional[int] = None,
    scan_results: Optional[list] = None,
) -> dict:
    """端到端摄入管线主入口

    Args:
        limit_md: markdown 文件数量上限（None 不限）
        limit_pdf: pdf/docx 文件数量上限（None 不限）
        scan_results: 外部注入的扫描结果（可选，用于指定文件类型子集）。
                     传入时忽略 limit_md/limit_pdf。

    Returns:
        统计 dict: {total, success, failed, chunks}
    """
    logger.info(f"启动摄入管线: limit_md={limit_md}, limit_pdf={limit_pdf}, "
                f"injected={scan_results is not None}")

    # 1. 扫描（若外部注入了 scan_results 则直接使用）
    if scan_results is None:
        scan_results = scan(limit_md, limit_pdf)
    if not scan_results:
        logger.warning("未扫描到任何文件")
        return {"total": 0, "success": 0, "failed": 0, "chunks": 0}

    stats = {"total": len(scan_results), "success": 0, "failed": 0, "chunks": 0}
    milvus_client = get_client()

    for i, sr in enumerate(scan_results, 1):
        logger.info(f"[{i}/{len(scan_results)}] 处理: {sr.rel_path}")
        doc_id: Optional[int] = None
        try:
            # a. 写 Document（status=pending）
            async with session_scope() as session:
                doc_id, already_embedded = await _get_or_create_document(session, sr)
            if already_embedded:
                logger.info(f"  跳过已摄入: {sr.rel_path}")
                continue

            # b. 解析
            await _update_doc_status(doc_id, DOC_STATUS_PARSING)
            parsed = await _parse_file(sr)
            await _update_doc_status(doc_id, DOC_STATUS_PARSED)

            # c. 切片（传 page_map 用于页码映射）
            chunks = chunk_text(parsed.text, page_map=parsed.page_map)
            if not chunks:
                logger.warning(f"  切片为空，标记完成: {sr.rel_path}")
                await _update_doc_status(doc_id, DOC_STATUS_EMBEDDED)
                stats["success"] += 1
                continue

            # d. 写 Chunks（milvus_id 暂空）
            # 若文档属于导师信息分类，尝试按文件名匹配 mentor_id
            mentor_id = None
            if sr.category == "导师信息":
                mentor_id = await _resolve_mentor_id(sr.rel_path)

            chunk_ids: list[int] = []
            async with session_scope() as session:
                for tc in chunks:
                    chunk = Chunk(
                        document_id=doc_id,
                        chunk_index=tc.index,
                        text_preview=tc.preview,
                        token_count=tc.token_count,
                        page_num=tc.page_num,
                        char_start=tc.char_start,
                        char_end=tc.char_end,
                        mentor_id=mentor_id,
                    )
                    session.add(chunk)
                    await session.flush()
                    chunk_ids.append(chunk.id)

            # e. 向量化
            await _update_doc_status(doc_id, DOC_STATUS_EMBEDDING)
            embeddings = embed([tc.text for tc in chunks])

            # f. 写 Milvus
            milvus_data = []
            for tc, emb in zip(chunks, embeddings):
                milvus_data.append({
                    "text": tc.text,
                    "dense": emb.dense,
                    "sparse": emb.sparse,
                    "doc_id": doc_id,
                    "category": sr.category or "",
                    "college": sr.college or "",
                    "subject": sr.subject or "",
                    "source_url": parsed.source_url or "",
                    "published_at": int(parsed.published_at.timestamp()) if parsed.published_at else 0,
                    # 原文位置元数据
                    "page_num": tc.page_num or 0,
                    "char_start": tc.char_start,
                    "char_end": tc.char_end,
                })
            milvus_ids = insert_chunks(milvus_client, milvus_data)

            # g. 回写 chunk.milvus_id + document.status=embedded
            async with session_scope() as session:
                for chunk_id, milvus_id in zip(chunk_ids, milvus_ids):
                    chunk = await session.get(Chunk, chunk_id)
                    if chunk:
                        chunk.milvus_id = milvus_id
                doc = await session.get(Document, doc_id)
                if doc:
                    doc.status = DOC_STATUS_EMBEDDED

            stats["success"] += 1
            stats["chunks"] += len(chunks)
            logger.info(f"  完成: {len(chunks)} 个 chunk, milvus_ids={milvus_ids[:3]}...")

        except Exception as e:
            logger.error(f"  摄入失败: {sr.rel_path}: {e}", exc_info=True)
            if doc_id is not None:
                await _update_doc_status(doc_id, DOC_STATUS_FAILED, str(e))
            stats["failed"] += 1

    logger.info(f"摄入完成: {stats}")
    return stats


def _parse_mentor_name_from_path(file_path: str) -> str | None:
    """从文件路径中解析导师姓名

    文件路径示例：
        导师信息/机电工程学院/机械类别/王阳_机电工程学院_机械类别.md
        导师信息/马克思主义学院/陈宪章_马克思主义学院.md
    返回第一个下划线前的内容作为姓名。
    """
    import re
    filename = Path(file_path).name
    filename = re.sub(r"\.(md|pdf|docx|doc)$", "", filename, flags=re.IGNORECASE)
    parts = filename.split("_", 1)
    name = parts[0].strip() if parts else filename.strip()
    if not name or len(name) < 2:
        return None
    return name


async def _resolve_mentor_id(file_path: str) -> int | None:
    """按文件名解析导师姓名，查 mentors 表，返回 mentor_id"""
    name = _parse_mentor_name_from_path(file_path)
    if not name:
        return None

    async with session_scope() as session:
        stmt = select(Mentor.id).where(Mentor.name == name)
        result = await session.execute(stmt)
        mid = result.scalar_one_or_none()

    if mid:
        logger.debug(f"导师匹配: {file_path} → {name} (mentor_id={mid})")
    return mid
