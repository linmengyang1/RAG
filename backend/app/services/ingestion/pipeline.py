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

from typing import Optional

from sqlalchemy import select

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
from app.services.ingestion.chunker import chunk_text
from app.services.ingestion.embedder import embed
from app.services.ingestion.markdown_parser import ParsedDoc, parse_markdown
from app.services.ingestion.milvus_writer import get_client, insert_chunks
from app.services.ingestion.mineru_client import get_mineru_client
from app.services.ingestion.scanner import ScanResult, scan


async def _parse_file(sr: ScanResult) -> ParsedDoc:
    """解析文件，返回 ParsedDoc

    md 文件用 markdown_parser（同步，不走网络）；
    pdf/docx 走 MinerU API（async）。
    """
    if sr.file_type == "md":
        parsed = parse_markdown(sr.path)
        # 路径推断的 college/subject 更可靠，覆盖 frontmatter 的值
        if sr.college:
            parsed.college = sr.college
        if sr.subject:
            parsed.subject = sr.subject
        return parsed

    # pdf/docx：走 MinerU
    client = get_mineru_client()
    result = await client.parse(sr.path)
    return ParsedDoc(
        text=result.markdown,
        college=sr.college,
        subject=sr.subject,
        page_map=result.page_map,  # 可能为 None（MinerU 不一定提供页码映射）
    )


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
) -> dict:
    """端到端摄入管线主入口

    Args:
        limit_md: markdown 文件数量上限（None 不限）
        limit_pdf: pdf/docx 文件数量上限（None 不限）

    Returns:
        统计 dict: {total, success, failed, chunks}
    """
    logger.info(f"启动摄入管线: limit_md={limit_md}, limit_pdf={limit_pdf}")

    # 1. 扫描
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
