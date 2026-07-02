"""CLI 入口：构建导师实体 + 关联 chunks

用法：
    docker compose exec backend python -m app.cli.build_mentors

步骤：
    1. 从 wiki person 条目反推 Mentor + MentorIdentity
    2. 将 category='导师信息' 文档的 chunks 关联到对应的 mentor
"""
from __future__ import annotations

import asyncio

from app.core.logging import logger
from app.services.mentor.builder import build_mentors_from_wiki, link_chunks_to_mentor


async def main():
    """主入口：构建导师实体 + 关联 chunks"""
    logger.info("========== 开始构建导师实体 ==========")

    # 步骤 1：从 wiki person 条目构建 Mentor
    logger.info("--- 步骤 1/2: 从 wiki person 条目构建 Mentor ---")
    result = await build_mentors_from_wiki()
    logger.info(
        f"步骤 1 完成: mentors={result['mentors']}, "
        f"identities={result['identities']}, merged={result['merged']}"
    )

    # 步骤 2：将 chunks 关联到 mentor
    logger.info("--- 步骤 2/2: 关联 chunks 到 Mentor ---")
    result2 = await link_chunks_to_mentor()
    logger.info(
        f"步骤 2 完成: linked={result2['linked']}, "
        f"unmatched_docs={result2['unmatched_docs']}"
    )

    logger.info("========== 导师实体构建完成 ==========")


if __name__ == "__main__":
    asyncio.run(main())
