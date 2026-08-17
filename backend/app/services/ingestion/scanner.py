"""文件扫描器：递归扫描 files_md 目录，列出待摄入的 md 文件

目录结构：
    output/files_md/{category}/{college_or_subdir}/{subject_or_none}/{file}.md

category 取 files_md/ 之后的第一级子目录名
（导师信息 / 研工工作 / 招生工作 / 培养工作）

所有文件均由 MinerU 预先解析为 md 格式，scanner 只扫描 .md 文件，不再调用 MinerU。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.document import DOC_SOURCE_WEB_MD


@dataclass
class ScanResult:
    """扫描结果：一个待摄入文件"""
    path: Path               # 绝对路径
    rel_path: str            # 相对 /data/output（用于去重）
    file_type: str           # md
    doc_source: str          # web_md
    category: Optional[str]  # 导师信息 / 研工工作 / 招生工作 / 培养工作
    college: Optional[str]   # 学院名（仅导师信息有）
    subject: Optional[str]   # 学科类别（仅导师信息有，如机械类别）


def _infer_metadata(rel_parts: list[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """从相对路径推断 category / college / subject

    rel_parts 示例：
        ['files_md', '导师信息', '机电工程学院', '机械类别', '王阳_机电工程学院_机械类别.md']
        ['files_md', '研工工作', '通知公告', '1092_思想政治教育.md']
    """
    # parts[0] 是 files_md/，从 parts[1] 开始
    category = rel_parts[1] if len(rel_parts) > 1 else None
    college = None
    subject = None

    if category == "导师信息":
        # 导师信息/{college}/{subject}/{file} 或 导师信息/{college}/{file}
        if len(rel_parts) > 2:
            college = rel_parts[2]
        if len(rel_parts) > 3:
            subject = rel_parts[3]

    return category, college, subject


def _scan_dir(
    base: Path,
    extensions: tuple[str, ...],
    limit: Optional[int] = None,
) -> list[ScanResult]:
    """扫描指定目录，返回指定扩展名的文件"""
    if not base.exists():
        logger.warning(f"扫描目录不存在: {base}")
        return []

    results: list[ScanResult] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue

        # 计算相对路径（相对于 output 根目录）
        output_root = Path(settings.data_output_dir)
        rel = path.relative_to(output_root)
        rel_path = str(rel).replace("\\", "/")
        rel_parts = rel_path.split("/")

        category, college, subject = _infer_metadata(rel_parts)

        results.append(ScanResult(
            path=path,
            rel_path=rel_path,
            file_type=path.suffix.lower().lstrip("."),
            doc_source=DOC_SOURCE_WEB_MD,
            category=category,
            college=college,
            subject=subject,
        ))

        if limit is not None and len(results) >= limit:
            break

    return results


def scan(
    limit_md: Optional[int] = None,
    limit_pdf: Optional[int] = None,
) -> list[ScanResult]:
    """扫描 files_md 目录

    Args:
        limit_md: markdown 文件数量上限（None 表示不限）
        limit_pdf: 废弃参数（保留兼容 CLI 调用，不再使用）

    Returns:
        ScanResult 列表
    """
    output_root = Path(settings.data_output_dir)
    md_dir = output_root / "files_md"

    logger.info(f"开始扫描: md_dir={md_dir}")

    md_results = _scan_dir(md_dir, (".md",), limit_md)

    logger.info(f"扫描完成: md={len(md_results)}, 总计={len(md_results)}")
    return md_results
