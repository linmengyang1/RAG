"""文本切片器：按 markdown 标题 + 段落累积切分

策略：
    1. 优先按 markdown 标题（## 或 ###）切分成 section
    2. 每个 section 内按段落（\\n\\n）累积到 CHUNK_SIZE
    3. 超长 section 按 CHUNK_SIZE 硬切
    4. 相邻 chunk 有 CHUNK_OVERLAP 字符重叠

中文约 3 字符 ≈ 1 token，CHUNK_SIZE=1500 字符 ≈ 500 token。
BGE-M3 最大支持 8192 token，1500 字符远在安全范围内。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# 切片参数
CHUNK_SIZE = 1500        # 每块最大字符数（约 500 token）
CHUNK_OVERLAP = 300     # 相邻块重叠字符数（占 chunk 的 20%，保证跨块语义连续）


@dataclass
class TextChunk:
    """一个文本切片"""
    index: int          # 在原文中的序号（从 0 开始）
    text: str           # 切片正文
    token_count: int    # 粗略 token 估算（字符数 // 3）
    preview: str        # 前 200 字符预览
    char_start: int = 0                # 在原文中的起始字符位置
    char_end: int = 0                  # 在原文中的结束字符位置
    page_num: Optional[int] = None     # PDF 页码（md 文件为 None）


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文 3 字符 ≈ 1 token）"""
    return max(1, len(text) // 3)


def _hard_split(text: str, size: int) -> List[str]:
    """把超长文本硬切成 size 大小的块"""
    return [text[i:i + size] for i in range(0, len(text), size)]


def _split_by_markdown_headers(text: str) -> list[tuple[int, int, str]]:
    """按 markdown 标题（## 或 ###）切分成 section

    返回 [(start, end, section_text), ...]，start/end 是在原文中的字符位置。
    标题行本身包含在 section_text 中。
    如果没有标题，返回整段文本作为一个 section。
    """
    # 匹配 ## 或 ### 开头的行（不匹配 # 一级标题，因为通常只有一个）
    header_pattern = re.compile(r'^#{2,3}\s+', re.MULTILINE)

    matches = list(header_pattern.finditer(text))
    if not matches:
        # 没有标题结构，整体作为一个 section
        return [(0, len(text), text)] if text.strip() else []

    sections: list[tuple[int, int, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((start, start + len(text[start:end].rstrip()), section_text))

    # 如果第一个标题之前有内容（如 # 标题行），也作为一个 section
    if matches[0].start() > 0:
        pre_text = text[:matches[0].start()].strip()
        if pre_text:
            sections.insert(0, (0, matches[0].start(), pre_text))

    return sections


def _find_page_num(char_pos: int, page_map: Optional[List[Tuple[int, int, int]]]) -> Optional[int]:
    """根据字符位置在 page_map 中查找页码

    Args:
        char_pos: 字符位置
        page_map: [(page_num, page_char_start, page_char_end), ...]

    Returns:
        对应页码，找不到返回 None
    """
    if not page_map:
        return None
    for pn, ps, pe in page_map:
        if ps <= char_pos < pe:
            return pn
    # 兜底：返回最后一页（防止越界）
    if page_map:
        return page_map[-1][0]
    return None


def chunk_text(
    text: str,
    page_map: Optional[List[Tuple[int, int, int]]] = None,
) -> List[TextChunk]:
    """把长文本切成 chunk 列表

    切分优先级：markdown 标题（##/###）> 段落（\\n\\n）> 硬切

    Args:
        text: 原始正文
        page_map: 可选页码映射 [(page_num, page_char_start, page_char_end), ...]
                  用于把 chunk 的 char_start 映射到 PDF 页码（md 文件传 None）

    Returns:
        TextChunk 列表（至少 1 个，空文本返回空列表）
    """
    text = text.strip()
    if not text:
        return []

    # 第一步：按 markdown 标题切分成 section
    sections = _split_by_markdown_headers(text)
    if not sections:
        return []

    # 第二步：每个 section 内按段落累积成 chunk
    raw_chunks: list[tuple[int, int, str]] = []  # [(start, end, text)]

    for sec_start, sec_end, sec_text in sections:
        # section 本身不超 CHUNK_SIZE：直接作为一个 chunk
        if len(sec_text) <= CHUNK_SIZE:
            raw_chunks.append((sec_start, sec_start + len(sec_text), sec_text))
            continue

        # section 超长：按段落累积切分
        paragraphs: list[tuple[int, int, str]] = []
        cursor = 0
        for raw in sec_text.split("\n\n"):
            if not raw.strip():
                cursor += len(raw) + 2
                continue
            p = raw.strip()
            start = sec_text.find(p, cursor)
            if start == -1:
                start = cursor
            end = start + len(p)
            paragraphs.append((start, end, p))
            cursor = end

        if not paragraphs:
            continue

        cur_start: Optional[int] = None
        cur_end: int = 0
        cur_text: str = ""

        for start, end, p in paragraphs:
            # 段落本身超长：硬切
            if len(p) > CHUNK_SIZE:
                if cur_text:
                    raw_chunks.append((sec_start + cur_start, sec_start + cur_end, cur_text))
                    cur_text = ""
                    cur_start = None
                for i in range(0, len(p), CHUNK_SIZE):
                    piece = p[i:i + CHUNK_SIZE]
                    raw_chunks.append((sec_start + start + i, sec_start + start + i + len(piece), piece))
                continue

            # 累积到 CHUNK_SIZE
            if cur_text and len(cur_text) + len(p) + 2 > CHUNK_SIZE:
                raw_chunks.append((sec_start + cur_start, sec_start + cur_end, cur_text))
                cur_text = p
                cur_start, cur_end = start, end
            else:
                if cur_text:
                    cur_text = f"{cur_text}\n\n{p}"
                    cur_end = end
                else:
                    cur_text = p
                    cur_start, cur_end = start, end

        if cur_text:
            raw_chunks.append((sec_start + cur_start, sec_start + cur_end, cur_text))

    if not raw_chunks:
        return []

    chunks = raw_chunks

    # 第三步：加 overlap（相邻 chunk 尾部拼接）
    if len(chunks) > 1 and CHUNK_OVERLAP > 0:
        overlapped: list[tuple[int, int, str]] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_start, prev_end, prev_text = chunks[i - 1]
            cur_start, cur_end, cur_text = chunks[i]
            prev_tail = prev_text[-CHUNK_OVERLAP:]
            new_start = max(0, cur_start - CHUNK_OVERLAP)
            overlapped.append((new_start, cur_end, f"{prev_tail}\n\n{cur_text}"))
        chunks = overlapped

    # 包装成 TextChunk
    result = [
        TextChunk(
            index=i,
            text=c_text,
            token_count=_estimate_tokens(c_text),
            preview=c_text[:200],
            char_start=c_start,
            char_end=c_end,
            page_num=_find_page_num(c_start, page_map),
        )
        for i, (c_start, c_end, c_text) in enumerate(chunks)
    ]
    return result
