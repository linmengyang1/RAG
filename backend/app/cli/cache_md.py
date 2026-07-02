"""MinerU md 缓存填充 CLI

遍历 output/files/ 下所有 PDF/DOCX，调用 MinerU API 解析，
将 md 文件保存到 output/files_md/（保持相同目录结构）。

已存在缓存的跳过，幂等可重跑。

用法：
    docker compose exec backend python -m app.cli.cache_md
"""
import argparse
import asyncio
from pathlib import Path

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.services.ingestion.mineru_client import get_mineru_client


def _target_md_path(file_path: Path, output_root: Path) -> Path:
    """计算目标 md 缓存路径

    /data/output/files/培养工作/答辩公告/1173_xxx.pdf
        → /data/output/files_md/培养工作/答辩公告/1173_xxx.md
    """
    try:
        rel = file_path.relative_to(output_root / "files")
    except ValueError:
        rel = file_path.relative_to(output_root)
    return (output_root / "files_md" / rel).with_suffix(".md")


async def run_cache_fill() -> dict:
    """遍历 files/ 下所有 PDF/DOCX，调 MinerU 解析并缓存"""
    client = get_mineru_client()
    output_root = Path(settings.data_output_dir)
    files_dir = output_root / "files"

    if not files_dir.exists():
        logger.error(f"源目录不存在: {files_dir}")
        return {"total": 0, "cached": 0, "skipped": 0, "failed": 0}

    # 收集所有 PDF/DOCX 文件
    all_files: list[Path] = []
    for ext in (".pdf", ".docx"):
        all_files.extend(sorted(files_dir.rglob(f"*{ext}")))

    if not all_files:
        logger.warning("未找到 PDF/DOCX 文件")
        return {"total": 0, "cached": 0, "skipped": 0, "failed": 0}

    stats = {"total": len(all_files), "cached": 0, "skipped": 0, "failed": 0}

    for i, file_path in enumerate(all_files, 1):
        target = _target_md_path(file_path, output_root)

        # 已有缓存则跳过
        if target.exists():
            logger.info(f"[{i}/{len(all_files)}] 跳过已有缓存: {target.name}")
            stats["skipped"] += 1
            continue

        try:
            logger.info(f"[{i}/{len(all_files)}] 解析: {file_path.name}")
            result = await client.parse(str(file_path))

            # 保存 md 到 files_md
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.markdown, encoding="utf-8")
            logger.info(f"  已保存: {target}")
            stats["cached"] += 1

        except Exception as e:
            logger.error(f"  解析失败: {file_path.name}: {e}")
            stats["failed"] += 1

    logger.info(f"缓存填充完成: {stats}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="MinerU md 缓存填充")
    parser.parse_args()

    setup_logging()
    stats = asyncio.run(run_cache_fill())
    print(f"\n缓存填充完成: {stats}")


if __name__ == "__main__":
    main()
