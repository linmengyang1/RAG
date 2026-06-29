"""文本切片器：把长文本切成 ~500 字符的 chunk

策略：
    1. 优先按段落（\\n\\n）切
    2. 累积段落直到接近 CHUNK_SIZE 字符
    3. 超长段落按 CHUNK_SIZE 硬切
    4. 相邻 chunk 有 CHUNK_OVERLAP 字符重叠

中文约 3 字符 ≈ 1 token，CHUNK_SIZE=500 字符 ≈ 167 token。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

# 切片参数
CHUNK_SIZE = 500         # 每块最大字符数（约 167 token）
CHUNK_OVERLAP = 200      # 相邻块重叠字符数（占 chunk 的 40%，保证跨块语义连续）


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

    # 按段落分割并记录每个段落在原文中的 (start, end) 位置
    paragraphs: list[tuple[int, int, str]] = []  # [(start, end, text)]
    cursor = 0
    for raw in text.split("\n\n"):
        if not raw.strip():
            cursor += len(raw) + 2  # +2 是 \n\n
            continue
        p = raw.strip()
        # 查找段落 p 在 text 中的位置（从 cursor 开始）
        start = text.find(p, cursor)
        if start == -1:
            start = cursor  # 兜底
        end = start + len(p)
        paragraphs.append((start, end, p))
        cursor = end

    if not paragraphs:
        return []

    # 累积段落成 chunk，跟踪 (char_start, char_end)
    chunks: list[tuple[int, int, str]] = []  # [(start, end, text)]
    cur_start: Optional[int] = None
    cur_end: int = 0
    cur_text: str = ""

    for start, end, p in paragraphs:
        # 段落本身超长：先把当前累积的存入，再硬切段落
        if len(p) > CHUNK_SIZE:
            if cur_text:
                chunks.append((cur_start, cur_end, cur_text))
                cur_text = ""
                cur_start = None
            # 硬切超长段落，每段记录对应位置
            for i in range(0, len(p), CHUNK_SIZE):
                piece = p[i:i + CHUNK_SIZE]
                chunks.append((start + i, start + i + len(piece), piece))
            continue

        # 累积到 CHUNK_SIZE
        if cur_text and len(cur_text) + len(p) + 2 > CHUNK_SIZE:  # +2 是 \n\n
            chunks.append((cur_start, cur_end, cur_text))
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
        chunks.append((cur_start, cur_end, cur_text))

    # 加 overlap：每个 chunk 前面拼上一个 chunk 的尾部
    if len(chunks) > 1 and CHUNK_OVERLAP > 0:
        overlapped: list[tuple[int, int, str]] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_start, prev_end, prev_text = chunks[i - 1]
            cur_start, cur_end, cur_text = chunks[i]
            prev_tail = prev_text[-CHUNK_OVERLAP:]
            # overlap 部分：char_start 回退 overlap 字符（不小于 0）
            new_start = max(0, cur_start - CHUNK_OVERLAP)
            overlapped.append((new_start, cur_end, f"{prev_tail}\n\n{cur_text}"))
        chunks = overlapped

    # 包装成 TextChunk，查 page_num
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
