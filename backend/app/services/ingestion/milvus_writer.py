"""Milvus 写入器：批量插入 chunk + 向量，返回 milvus 自增 id

chunks 集合 schema（见 infra/scripts/init_milvus.py）：
    id: INT64, auto_id, primary
    dense: FLOAT_VECTOR(1024)
    sparse: SPARSE_FLOAT_VECTOR
    text: VARCHAR(8192)
    doc_id: INT64
    category: VARCHAR(64)
    college: VARCHAR(128)
    subject: VARCHAR(128)
    source_url: VARCHAR(512)
    published_at: INT64 (时间戳)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pymilvus import MilvusClient

from app.core.config import settings
from app.core.logging import logger


def get_client() -> MilvusClient:
    """获取 MilvusClient（每次新建，pymilvus 内部会复用连接池）"""
    return MilvusClient(uri=settings.milvus_uri)


def insert_chunks(
    client: MilvusClient,
    chunks: list[dict],
) -> List[int]:
    """批量插入 chunk 到 Milvus chunks 集合

    Args:
        client: MilvusClient 实例
        chunks: 待插入的数据列表，每个元素是 dict，包含：
            - text: str               (必填)
            - dense: list[float]      (必填，1024 维)
            - sparse: dict[int, float](必填)
            - doc_id: int             (必填)
            - category: str | None
            - college: str | None
            - subject: str | None
            - source_url: str | None
            - published_at: int | None(时间戳，0 表示未知)

    Returns:
        milvus 自增 id 列表（顺序与输入一致）
    """
    if not chunks:
        return []

    # 规范化字段：None 转成空字符串或 0（Milvus VARCHAR 不接受 None）
    data = []
    for c in chunks:
        item = {
            "text": c["text"][:8192],   # 截断到 schema 上限
            "dense": c["dense"],
            "sparse": c["sparse"],
            "doc_id": c["doc_id"],
            "category": (c.get("category") or "")[:64],
            "college": (c.get("college") or "")[:128],
            "subject": (c.get("subject") or "")[:128],
            "source_url": (c.get("source_url") or "")[:512],
            "published_at": c.get("published_at") or 0,
            # 原文位置元数据（None 转 0）
            "page_num": c.get("page_num") or 0,
            "char_start": c.get("char_start") or 0,
            "char_end": c.get("char_end") or 0,
        }
        data.append(item)

    collection = settings.milvus_collection_chunks
    logger.info(f"插入 Milvus: collection={collection}, count={len(data)}")

    result = client.insert(collection_name=collection, data=data)
    # MilvusClient.insert 返回 {'insert_count': n, 'ids': [...]}
    ids = result.get("ids", []) if isinstance(result, dict) else []
    logger.info(f"Milvus 插入完成: {len(ids)} 条, ids 示例={ids[:3]}")
    return list(ids)


def delete_by_doc_id(client: MilvusClient, doc_id: int) -> int:
    """删除某个 document 的所有 chunk（按 doc_id 过滤）"""
    collection = settings.milvus_collection_chunks
    result = client.delete(
        collection_name=collection,
        filter=f"doc_id == {doc_id}",
    )
    deleted = result.get("delete_count", 0) if isinstance(result, dict) else 0
    logger.info(f"Milvus 删除 doc_id={doc_id}: {deleted} 条")
    return deleted
