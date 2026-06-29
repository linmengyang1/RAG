"""DeepSeek LLM API 客户端

接入真实 DeepSeek API（OpenAI 兼容格式）。
官方文档：https://api-docs.deepseek.com/

调用方约定：
    client = get_llm_client()
    async for chunk in client.chat_stream(messages, model="deepseek-v4-flash"):
        ...  # str 增量
    answer = await client.generate(prompt, model="deepseek-v4-pro")  # 完整字符串
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol

import httpx

from app.core.config import settings
from app.core.logging import logger


class LLMClient(Protocol):
    async def chat_stream(
        self, messages: list[dict], model: str | None = None
    ) -> AsyncIterator[str]:
        ...

    async def generate(self, prompt: str, model: str | None = None) -> str:
        ...


class LLMMockClient:
    """占位实现：模拟流式输出（仅在未配置 API key 时启用）"""

    MOCK_ANSWER = (
        "[MOCK LLM] 当前为占位响应。请在 .env 中填入 DEEPSEEK_API_KEY "
        "并设置 LLM_USE_MOCK=false 以启用真实的 DeepSeek API。\n\n"
        "收到的问题：{question}"
    )

    async def chat_stream(
        self, messages: list[dict], model: str | None = None
    ) -> AsyncIterator[str]:
        question = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "(空)",
        )
        text = self.MOCK_ANSWER.format(question=question)
        for i in range(0, len(text), 4):
            yield text[i : i + 4]
            await asyncio.sleep(0.05)

    async def generate(self, prompt: str, model: str | None = None) -> str:
        await asyncio.sleep(0.3)
        return f"[MOCK LLM] generate({model or 'main'}): {prompt[:200]}"


class DeepSeekClient:
    """真实 DeepSeek API 实现（OpenAI Chat Completions 兼容）。

    使用 httpx 直接调 POST {base}/chat/completions。
    base_url 默认 https://api.deepseek.com（无需 /v1 后缀，SDK 会处理）。
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.deepseek_api_base,
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
        )

    async def chat_stream(
        self, messages: list[dict], model: str | None = None
    ) -> AsyncIterator[str]:
        resp = await self._client.post(
            "/chat/completions",
            json={
                "model": model or settings.deepseek_main_model,
                "messages": messages,
                "stream": True,
            },
        )
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            import orjson
            chunk = orjson.loads(payload)
            delta = chunk["choices"][0].get("delta", {}).get("content")
            if delta:
                yield delta

    async def generate(self, prompt: str, model: str | None = None) -> str:
        chunks = []
        async for c in self.chat_stream(
            [{"role": "user", "content": prompt}],
            model=model or settings.deepseek_wiki_model,
        ):
            chunks.append(c)
        return "".join(chunks)

    async def close(self) -> None:
        await self._client.aclose()


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """工厂：根据配置选择 mock 或真实实现"""
    global _client
    if _client is None:
        if settings.llm_should_use_mock:
            logger.warning("LLM 走 mock 实现（DEEPSEEK_API_KEY 未配置）")
            _client = LLMMockClient()
        else:
            logger.info(
                f"LLM 走真实 DeepSeek API (base={settings.deepseek_api_base}, "
                f"main={settings.deepseek_main_model}, wiki={settings.deepseek_wiki_model})"
            )
            _client = DeepSeekClient()
    return _client
