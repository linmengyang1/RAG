"""MinerU API 客户端

接入真实 MinerU 精准解析 API。
官方文档：https://mineru.net/apiManage/docs

流程（本地文件）：
  1. POST /file-urls/batch 申请上传链接 → 返回 batch_id + file_urls[]
  2. PUT 文件到 file_urls[i]（系统自动开始解析）
  3. 轮询 GET /extract-results/batch/{batch_id}
  4. 下载 full_zip_url，解压取 markdown + images

调用方约定：
    client = get_mineru_client()
    result: MarkdownResult = await client.parse(file_path)
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.logging import logger


# MinerU 不同版本 json 中页码字段的候选名
_PAGE_FIELD_CANDIDATES = ("page_idx", "page_no", "page_num", "page_id", "page_index")
# 文本字段候选名（顶层或 block 中）
_TEXT_FIELD_CANDIDATES = ("text", "content", "markdown", "content_md")
# 块列表字段候选名
_BLOCKS_FIELD_CANDIDATES = ("blocks", "sub_blocks", "sub_blocks_preproc")


def _try_extract_page_map(zip_bytes: bytes, markdown_text: str) -> list[tuple[int, int, int]] | None:
    """best-effort 从 MinerU zip 中提取页码与字符区间映射

    MinerU 不同版本 json 结构不同，本函数尝试多种字段名兼容解析。
    策略：
        1. 找 zip 中的 .json 文件（排除明显非布局文件）
        2. 解析为 list[dict] 或 dict
        3. 每页找 page 字段 + text/blocks.text 字段
        4. 拼接每页文本，在 markdown_text 中查找匹配建立 char_start/char_end
    失败时返回 None，不影响主流程。

    Returns:
        [(page_num, char_start, char_end), ...] 或 None
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            json_files = [
                name for name in zf.namelist()
                if name.endswith(".json") and "images" not in name
            ]
            if not json_files:
                return None

            # 优先 model.json / layout.json / origin.json
            priority = ["model.json", "layout.json", "origin.json", "content_list.json"]
            json_files.sort(key=lambda n: priority.index(n) if n in priority else 99)

            for jf_name in json_files:
                try:
                    raw = zf.read(jf_name).decode("utf-8", errors="ignore")
                    data = json.loads(raw)
                except Exception:
                    continue

                pages = _extract_pages_from_json(data)
                if not pages:
                    continue

                # pages: [(page_num, page_text), ...]，按 page_num 排序
                pages.sort(key=lambda x: x[0])

                # 在 markdown_text 中按顺序匹配每页文本，建立 char 区间
                page_map: list[tuple[int, int, int]] = []
                cursor = 0
                for page_num, page_text in pages:
                    if not page_text:
                        # 空页：占 0 字符，cursor 不动
                        page_map.append((page_num, cursor, cursor))
                        continue
                    # 在 markdown_text 中从 cursor 开始查找 page_text 的前 50 字符
                    snippet = page_text.strip()[:50]
                    if not snippet:
                        page_map.append((page_num, cursor, cursor))
                        continue
                    pos = markdown_text.find(snippet, max(0, cursor - 100))
                    if pos == -1:
                        # 找不到匹配，用累积长度近似
                        page_map.append((page_num, cursor, cursor))
                        continue
                    # 该页字符区间 [pos, pos + len(page_text)]
                    page_end = pos + len(page_text)
                    page_map.append((page_num, pos, page_end))
                    cursor = page_end

                # 验证：至少有 1 页成功映射
                valid = [p for p in page_map if p[1] != p[2]]
                if valid:
                    logger.info(
                        f"MinerU 页码解析成功: {jf_name}, "
                        f"共 {len(pages)} 页，成功映射 {len(valid)} 页"
                    )
                    return page_map
        return None
    except Exception as e:
        logger.debug(f"_try_extract_page_map 失败: {e}")
        return None


def _extract_pages_from_json(data) -> list[tuple[int, str]] | None:
    """从 MinerU json 中提取 [(page_num, page_text), ...]

    支持的结构：
        - list[dict]：每个 dict 是一页
        - dict 含 pages 字段：data["pages"] 是 list[dict]
    """
    pages: list[tuple[int, str]] = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # 找 list 类型的字段
        items = None
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                items = v
                break
        if items is None:
            return None
    else:
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        # 找页码字段
        page_num = None
        for f in _PAGE_FIELD_CANDIDATES:
            if f in item and isinstance(item[f], int):
                page_num = item[f]
                break
        if page_num is None:
            continue

        # 找文本：先看顶层 text 字段，再看 blocks 中的 text
        page_text = ""
        for f in _TEXT_FIELD_CANDIDATES:
            v = item.get(f)
            if isinstance(v, str) and v.strip():
                page_text = v
                break

        if not page_text:
            # 从 blocks 中累积
            for f in _BLOCKS_FIELD_CANDIDATES:
                blocks = item.get(f)
                if isinstance(blocks, list):
                    for b in blocks:
                        if isinstance(b, dict):
                            for tf in _TEXT_FIELD_CANDIDATES:
                                bt = b.get(tf)
                                if isinstance(bt, str) and bt.strip():
                                    page_text += bt + "\n"
                                    break
                    if page_text:
                        break

        pages.append((page_num, page_text))

    return pages if pages else None


@dataclass
class MarkdownResult:
    markdown: str
    images: dict[str, bytes] = field(default_factory=dict)
    raw_json: dict | None = None
    batch_id: str | None = None
    task_id: str | None = None
    # 页码映射 [(page_num, page_char_start, page_char_end), ...]
    # 用于把 chunk 的 char_start 映射到 PDF 页码
    # 仅 PDF/DOCX 通过 MinerU 解析时可能填充；解析失败为 None
    page_map: list[tuple[int, int, int]] | None = None


class MinerUClient(Protocol):
    async def parse(self, file_path: str | Path) -> MarkdownResult:
        ...


class MinerUMockClient:
    """占位实现：直接读取 .md / .txt；其他类型返回占位文本"""

    async def parse(self, file_path: str | Path) -> MarkdownResult:
        path = Path(file_path)
        if path.suffix.lower() in (".md", ".txt"):
            text = path.read_text(encoding="utf-8", errors="ignore")
        else:
            raw = path.read_bytes() if path.exists() else b""
            sha = hashlib.sha256(raw).hexdigest()[:16]
            text = (
                f"[MOCK MinerU] 占位解析结果\n\n"
                f"文件：{path.name}\nsha256[:16]: {sha}\n\n"
                f"请在 .env 中填入 MINERU_API_TOKEN 并设置 MINERU_USE_MOCK=false。"
            )
        await asyncio.sleep(0.1)
        return MarkdownResult(markdown=text)


class MinerURealClient:
    """真实 MinerU API 实现。

    本地文件走 batch 上传流程；公网 URL 走 /extract/task 单文件流程。
    """

    def __init__(self) -> None:
        self._api_base = settings.mineru_api_base.rstrip("/")
        self._token = settings.mineru_api_token
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(timeout=300.0)

    async def parse(self, file_path: str | Path) -> MarkdownResult:
        path = Path(file_path)
        # 已是 markdown/txt 的直接读（不入 MinerU 节省配额）
        if path.suffix.lower() in (".md", ".txt"):
            return MarkdownResult(markdown=path.read_text(encoding="utf-8", errors="ignore"))

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")

        if str(path).startswith(("http://", "https://")):
            return await self._parse_url(str(path))

        return await self._parse_local_file(path)

    async def _parse_local_file(self, path: Path) -> MarkdownResult:
        """本地文件：申请上传链接 → PUT → 轮询 batch → 下载 zip"""
        # 1. 申请上传链接（用 batch 接口但只传 1 个文件）
        apply_resp = await self._client.post(
            f"{self._api_base}/file-urls/batch",
            headers=self._headers,
            json={
                "files": [{"name": path.name}],
                "model_version": settings.mineru_model_version,
                "enable_formula": settings.mineru_enable_formula,
                "enable_table": settings.mineru_enable_table,
                "language": settings.mineru_language,
            },
        )
        apply_resp.raise_for_status()
        body = apply_resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"MinerU 申请上传链接失败: {body.get('msg')}")

        batch_id = body["data"]["batch_id"]
        upload_url = body["data"]["file_urls"][0]
        logger.info(f"MinerU 申请到上传链接 batch_id={batch_id}, file={path.name}")

        # 2. PUT 上传文件（不要设 Content-Type）
        with path.open("rb") as f:
            put_resp = await self._client.put(upload_url, content=f.read())
        put_resp.raise_for_status()
        logger.info(f"MinerU 文件上传完成: {path.name}")

        # 3. 轮询 batch 结果
        result = await self._poll_batch(batch_id)
        result.batch_id = batch_id
        return result

    async def _parse_url(self, url: str) -> MarkdownResult:
        """公网 URL：走 /extract/task 单文件流程"""
        submit_resp = await self._client.post(
            f"{self._api_base}/extract/task",
            headers=self._headers,
            json={
                "url": url,
                "model_version": settings.mineru_model_version,
                "enable_formula": settings.mineru_enable_formula,
                "enable_table": settings.mineru_enable_table,
                "language": settings.mineru_language,
            },
        )
        submit_resp.raise_for_status()
        body = submit_resp.json()
        if body.get("code") != 0:
            raise RuntimeError(f"MinerU 提交任务失败: {body.get('msg')}")

        task_id = body["data"]["task_id"]
        logger.info(f"MinerU 提交任务 task_id={task_id}, url={url[:80]}")

        result = await self._poll_task(task_id)
        result.task_id = task_id
        return result

    async def _poll_batch(self, batch_id: str) -> MarkdownResult:
        """轮询 batch 结果直到 done 或 failed"""
        deadline = asyncio.get_event_loop().time() + settings.mineru_timeout
        url = f"{self._api_base}/extract-results/batch/{batch_id}"

        while asyncio.get_event_loop().time() < deadline:
            resp = await self._client.get(url, headers=self._headers)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 0:
                raise RuntimeError(f"MinerU 查询 batch 失败: {body.get('msg')}")

            results = body["data"].get("extract_result", [])
            if not results:
                await asyncio.sleep(settings.mineru_poll_interval)
                continue

            # batch 模式下我们只传了 1 个文件，取第 1 个
            item = results[0]
            state = item.get("state")
            if state == "done":
                return await self._download_zip(item["full_zip_url"])
            if state == "failed":
                raise RuntimeError(f"MinerU 解析失败: {item.get('err_msg')}")
            logger.debug(f"MinerU batch 状态: {state}")
            await asyncio.sleep(settings.mineru_poll_interval)

        raise TimeoutError(f"MinerU batch {batch_id} 超时")

    async def _poll_task(self, task_id: str) -> MarkdownResult:
        deadline = asyncio.get_event_loop().time() + settings.mineru_timeout
        url = f"{self._api_base}/extract/task/{task_id}"

        while asyncio.get_event_loop().time() < deadline:
            resp = await self._client.get(url, headers=self._headers)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != 0:
                raise RuntimeError(f"MinerU 查询 task 失败: {body.get('msg')}")

            data = body["data"]
            state = data.get("state")
            if state == "done":
                return await self._download_zip(data["full_zip_url"])
            if state == "failed":
                raise RuntimeError(f"MinerU 解析失败: {data.get('err_msg')}")
            progress = data.get("extract_progress")
            if progress:
                logger.debug(
                    f"MinerU task {task_id}: {state} "
                    f"{progress.get('extracted_pages', '?')}/{progress.get('total_pages', '?')}"
                )
            await asyncio.sleep(settings.mineru_poll_interval)

        raise TimeoutError(f"MinerU task {task_id} 超时")

    async def _download_zip(self, zip_url: str) -> MarkdownResult:
        """下载 zip 并解压，提取 markdown + images + 页码映射"""
        resp = await self._client.get(zip_url)
        resp.raise_for_status()

        markdown = ""
        images: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if name.endswith(".md") and not markdown:
                    markdown = zf.read(name).decode("utf-8", errors="ignore")
                elif name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp")):
                    # 用相对路径作为 key（chunker 拼接图片引用时用）
                    images[name] = zf.read(name)

        # best-effort 解析页码映射（失败为 None，不影响主流程）
        page_map = _try_extract_page_map(resp.content, markdown)

        logger.info(
            f"MinerU 下载完成: markdown={len(markdown)} chars, "
            f"images={len(images)}, page_map={'有' if page_map else '无'}"
        )
        return MarkdownResult(markdown=markdown, images=images, page_map=page_map)

    async def close(self) -> None:
        await self._client.aclose()


_client: MinerUClient | None = None


def get_mineru_client() -> MinerUClient:
    global _client
    if _client is None:
        if settings.mineru_should_use_mock:
            logger.warning("MinerU 走 mock 实现（MINERU_API_TOKEN 未配置）")
            _client = MinerUMockClient()
        else:
            logger.info(f"MinerU 走真实 API (base={settings.mineru_api_base})")
            _client = MinerURealClient()
    return _client
