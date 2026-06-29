"""摄入管线 CLI 入口

用法：
    docker compose exec backend python -m app.cli.ingest --limit-md 24 --limit-pdf 5
    docker compose exec backend python -m app.cli.ingest            # 全量摄入
"""
import argparse
import asyncio

from app.core.logging import setup_logging
from app.services.ingestion.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="运行数据摄入管线")
    parser.add_argument(
        "--limit-md", type=int, default=None,
        help="markdown 文件数量上限（不传则不限）",
    )
    parser.add_argument(
        "--limit-pdf", type=int, default=None,
        help="pdf/docx 文件数量上限（不传则不限）",
    )
    args = parser.parse_args()

    setup_logging()
    stats = asyncio.run(run_pipeline(args.limit_md, args.limit_pdf))
    print(f"\n摄入完成: {stats}")


if __name__ == "__main__":
    main()
