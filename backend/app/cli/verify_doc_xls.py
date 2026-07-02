"""验证 14 个 .doc/.xls/.xlsx 文件摄入

直接调 scanner._scan_dir 只扫 doc/xls/xlsx 类型，
绕过 limit_pdf 的路径排序问题（前 N 个可能都是 pdf/docx）。

用法：
    docker compose exec backend python -m app.cli.verify_doc_xls
"""
import asyncio
import time
from pathlib import Path

from pymilvus import MilvusClient

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.models.document import DOC_SOURCE_ATTACHMENT
from app.services.ingestion.pipeline import run_pipeline
from app.services.ingestion.scanner import _scan_dir


def wait_for_milvus(timeout: int = 120) -> bool:
    """等待 Milvus 就绪"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            c = MilvusClient(uri=settings.milvus_uri)
            c.flush(settings.milvus_collection_chunks)
            stats = c.get_collection_stats(settings.milvus_collection_chunks)
            logger.info(f"Milvus 就绪，当前向量数: {stats}")
            return True
        except Exception as e:
            logger.warning(f"等待 Milvus 就绪... ({e})")
            time.sleep(3)
    return False


def scan_doc_xls_xlsx() -> list:
    """只扫描 doc/xls/xlsx 文件"""
    output_root = Path(settings.data_output_dir)
    files_dir = output_root / "files"
    results = _scan_dir(
        files_dir, DOC_SOURCE_ATTACHMENT,
        (".doc", ".xls", ".xlsx"),
        limit=None,
    )
    return results


async def main() -> None:
    setup_logging()

    # 1. 等 Milvus 就绪
    logger.info("=== 步骤 1: 等待 Milvus 就绪 ===")
    if not wait_for_milvus(120):
        logger.error("Milvus 120 秒内未就绪，退出")
        return

    # 2. 扫描 doc/xls/xlsx
    logger.info("=== 步骤 2: 扫描 doc/xls/xlsx 文件 ===")
    results = scan_doc_xls_xlsx()
    logger.info(f"扫描到 {len(results)} 个 doc/xls/xlsx 文件:")
    for r in results:
        logger.info(f"  [{r.file_type}] {r.rel_path}")

    if not results:
        logger.warning("未扫到任何 doc/xls/xlsx 文件")
        return

    # 3. 调 run_pipeline 注入 scan_results
    logger.info("=== 步骤 3: 启动摄入 ===")
    stats = await run_pipeline(scan_results=results)
    print(f"\n摄入完成: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
