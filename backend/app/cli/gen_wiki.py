"""CLI 入口：从导师信息类文档生成 wiki 条目

用法：
    docker exec grad-rag-backend bash -c "cd /app && python -m app.cli.gen_wiki"

范围：
    仅对 category='导师信息' 的文档（含导师信息汇总.md，共约 295 个）生成 wiki。
    其他分类（培养工作/招生工作/研工工作/研究生文件）不生成，价值不高。

模型：deepseek-v4-flash（见 .env DEEPSEEK_WIKI_MODEL）

步骤：
    1. 从 PG 查询 category='导师信息' 的所有 document id
    2. 调 generate_wiki_entries(doc_ids=...) 限定范围生成
    3. 内部流程：Milvus 按 doc_id 过滤 chunks → 按 doc_id 分组拼接全文
       → 每 3 文档一批调 LLM 提取 person/policy/process → 去重 → 写 PG + Milvus
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.logging import logger
from app.db.session import session_scope
from app.models.document import Document
from app.services.wiki.generator import generate_wiki_entries


async def main():
    """主入口：从导师信息类文档生成 wiki 条目"""
    logger.info("========== 开始 wiki 生成（仅导师信息类文档）==========")

    # 1. 查询导师信息类文档的 doc_ids
    async with session_scope() as s:
        result = await s.execute(
            select(Document.id).where(Document.category == "导师信息")
        )
        doc_ids = [row[0] for row in result]

    if not doc_ids:
        logger.warning("没有 category='导师信息' 的文档，退出")
        return

    logger.info(f"共 {len(doc_ids)} 个导师信息类文档待生成 wiki")

    # 2. 调用 wiki 生成（limit 设大覆盖全部 chunks）
    stats = await generate_wiki_entries(doc_ids=doc_ids, limit=5000)
    logger.info(f"wiki 生成完成: {stats}")
    logger.info("========== wiki 生成结束 ==========")


if __name__ == "__main__":
    asyncio.run(main())
