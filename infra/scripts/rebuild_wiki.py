"""
重建 wiki 集合向量：从 PG wiki_entries 表读取数据 -> 向量化 -> 写入 Milvus wiki 集合

背景：etcd 元数据丢失后 wiki 集合被重建（row_count=0），但 PG wiki_entries 表
21 条记录保留完好。本脚本从 PG 重新读取，用 BGE-M3 向量化 content_summary，
写入 Milvus wiki 集合，恢复 wiki 检索能力。

用法：
    docker exec grad-rag-backend python /app/infra/scripts/rebuild_wiki.py
"""
from __future__ import annotations

import asyncio
import sys

# 确保能 import app 模块（容器内 WORKDIR=/app，但脚本在 /app/infra/scripts/ 下）
sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.models.wiki import WikiEntry  # noqa: E402
from app.services.ingestion.embedder import embed  # noqa: E402
from app.services.ingestion.milvus_writer import get_client  # noqa: E402


async def rebuild_wiki() -> None:
    """从 PG wiki_entries 重新向量化写入 Milvus wiki 集合"""
    print("[rebuild_wiki] 开始重建 wiki 向量")

    # 1. 读取 PG wiki_entries 全部记录
    async with session_scope() as session:
        result = await session.execute(select(WikiEntry))
        entries = result.scalars().all()

    print(f"[rebuild_wiki] 读取 {len(entries)} 条 wiki_entries")
    if not entries:
        print("[rebuild_wiki] 无数据，退出")
        return

    # 2. 向量化（与 generator.py 一致：content_summary 优先，无则用 title）
    texts = [e.content_summary or e.title for e in entries]
    print(f"[rebuild_wiki] 开始向量化 {len(texts)} 段文本（BGE-M3）")
    embeddings = embed(texts)
    print(f"[rebuild_wiki] 向量化完成: {len(embeddings)} 个向量")

    # 3. 组装 Milvus 数据（字段映射与 generator.py 完全一致）
    wiki_data = []
    for e, emb in zip(entries, embeddings):
        wiki_data.append({
            "dense": emb.dense,
            "title": e.title[:255],
            "entry_type": e.entry_type[:32],
            "content": e.content_md[:32768],          # PG content_md -> Milvus content
            "summary": (e.content_summary or "")[:1024],  # PG content_summary -> Milvus summary
        })

    # 4. 写入 Milvus wiki 集合
    client = get_client()
    # 写入前先确认 wiki 集合存在
    if not client.has_collection(settings.milvus_collection_wiki):
        print(f"[rebuild_wiki] 错误：集合 {settings.milvus_collection_wiki} 不存在，先运行 init_milvus.py")
        return

    result = client.insert(
        collection_name=settings.milvus_collection_wiki,
        data=wiki_data,
    )
    ids = result.get("ids", []) if isinstance(result, dict) else []
    print(f"[rebuild_wiki] Milvus 写入完成: {len(ids)} 条, ids 示例={ids[:3]}")

    # 5. 验证
    stats = client.get_collection_stats(settings.milvus_collection_wiki)
    print(f"[rebuild_wiki] wiki 集合当前行数: {stats}")
    print("[rebuild_wiki] 重建完成!")


if __name__ == "__main__":
    asyncio.run(rebuild_wiki())
