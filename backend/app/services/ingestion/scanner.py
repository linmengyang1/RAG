"""文件扫描器：递归扫描 output 目录，列出待摄入文件

目录结构：
    output/markdown/{category}/{college_or_subdir}/{subject_or_none}/{file}.md
    output/files/{category}/{file}.pdf

category 取 markdown/ 或 files/ 之后的第一级子目录名
（导师信息 / 研工工作 / 招生工作 / 培养工作）
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import logger
from app.models.document import DOC_SOURCE_ATTACHMENT, DOC_SOURCE_WEB_MD


@dataclass
class ScanResult:
    """扫描结果：一个待摄入文件"""
    path: Path               # 绝对路径
    rel_path: str            # 相对 /data/output（用于去重）
    file_type: str           # md / pdf / docx
    doc_source: str          # web_md / attachment
    category: Optional[str]  # 导师信息 / 研工工作 / 招生工作 / 培养工作
    college: Optional[str]   # 学院名（仅导师信息有）
    subject: Optional[str]   # 学科类别（仅导师信息有，如机械类别）


def _infer_metadata(rel_parts: list[str], doc_source: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """从相对路径推断 category / college / subject

    rel_parts 示例：
        ['markdown', '导师信息', '机电工程学院', '机械类别', '王阳_机电工程学院_机械类别.md']
        ['markdown', '研工工作', '通知公告', '1092_思想政治教育.md']
        ['files', '导师信息', 'xxx.pdf']
    """
    # parts[0] 是 markdown/ 或 files/，从 parts[1] 开始
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
    doc_source: str,
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

        category, college, subject = _infer_metadata(rel_parts, doc_source)

        results.append(ScanResult(
            path=path,
            rel_path=rel_path,
            file_type=path.suffix.lower().lstrip("."),
            doc_source=doc_source,
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
    """扫描 output 目录，按 limit 抽样

    Args:
        limit_md: markdown 文件数量上限（None 表示不限）
        limit_pdf: pdf 文件数量上限（None 表示不限，docx 也计入此限额）

    Returns:
        ScanResult 列表
    """
    output_root = Path(settings.data_output_dir)
    md_dir = output_root / "markdown"
    files_dir = output_root / "files"

    logger.info(f"开始扫描: md_dir={md_dir}, files_dir={files_dir}")

    md_results = _scan_dir(md_dir, DOC_SOURCE_WEB_MD, (".md",), limit_md)
    # files/ 下支持 pdf/docx/doc/xls/xlsx（doc/docx/xls/xlsx 统一走 MinerU 解析）
    pdf_results = _scan_dir(
        files_dir, DOC_SOURCE_ATTACHMENT,
        (".pdf", ".docx", ".doc", ".xls", ".xlsx"),
        limit_pdf,
    )

    all_results = md_results + pdf_results
    logger.info(
        f"扫描完成: md={len(md_results)}, files={len(pdf_results)}, "
        f"总计={len(all_results)}"
    )
    return all_results
