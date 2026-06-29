"""Markdown 解析器：读取 md 文件 + frontmatter 元数据

使用 python-frontmatter 库（pyproject.toml 已声明依赖）。
frontmatter 中的字段会被提取为 ParsedDoc 的元数据。

支持的 frontmatter 字段：
    college: 学院
    subject: 学科
    source_url: 原始页面 URL
    published_at: 发布时间（ISO 格式字符串）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import frontmatter

from app.core.logging import logger


@dataclass
class ParsedDoc:
    """解析后的文档"""
    text: str                           # 正文（已去除 frontmatter）
    college: Optional[str] = None
    subject: Optional[str] = None
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    # 页码映射 [(page_num, page_char_start, page_char_end), ...]
    # 仅 PDF/DOCX 通过 MinerU 解析时可能填充；md 文件为 None
    page_map: Optional[List[Tuple[int, int, int]]] = None


def _parse_datetime(value) -> Optional[datetime]:
    """尝试解析日期时间字段（兼容多种格式）"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # 尝试常见格式
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
        ):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        logger.debug(f"无法解析日期: {value!r}")
    return None


def parse_markdown(path: Path) -> ParsedDoc:
    """解析 markdown 文件，返回正文 + 元数据

    如果文件没有 frontmatter，直接返回全文。
    """
    try:
        post = frontmatter.load(str(path))
    except Exception as e:
        logger.warning(f"frontmatter 解析失败 {path.name}: {e}，回退为纯文本")
        text = path.read_text(encoding="utf-8", errors="ignore")
        return ParsedDoc(text=text)

    text = post.content
    meta = post.metadata or {}

    return ParsedDoc(
        text=text,
        college=meta.get("college") or meta.get("学院"),
        subject=meta.get("subject") or meta.get("学科"),
        source_url=meta.get("source_url") or meta.get("url"),
        published_at=_parse_datetime(
            meta.get("published_at") or meta.get("date") or meta.get("发布时间")
        ),
    )
