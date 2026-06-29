"""P0 单元测试：config / security / 占位 LLM / MinerU 客户端"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# 测试用默认值
os.environ.setdefault("JWT_SECRET", "test-secret-1234567890")


def test_config_loads_with_defaults():
    from app.core.config import Settings
    s = Settings()
    assert s.app_name == "Graduate RAG"
    assert s.jwt_alg == "HS256"
    assert s.embed_dim == 1024
    assert s.milvus_collection_chunks == "chunks"
    assert s.milvus_collection_wiki == "wiki"
    assert isinstance(s.app_cors_origins, list)


def test_config_llm_mock_fallback():
    """未配置 DEEPSEEK_API_KEY 时应自动走 mock"""
    from app.core.config import Settings
    s = Settings(deepseek_api_key="", llm_use_mock=False)
    assert s.llm_should_use_mock is True

    s2 = Settings(deepseek_api_key="sk-xxx", llm_use_mock=False)
    assert s2.llm_should_use_mock is False


def test_config_mineru_mock_fallback():
    from app.core.config import Settings
    s = Settings(mineru_api_token="", mineru_use_mock=False)
    assert s.mineru_should_use_mock is True

    s2 = Settings(mineru_api_token="some-token", mineru_use_mock=False)
    assert s2.mineru_should_use_mock is False


def test_config_postgres_dsn():
    from app.core.config import Settings
    s = Settings(
        postgres_user="u", postgres_password="p",
        postgres_host="h", postgres_port=5432, postgres_db="d",
    )
    assert s.postgres_dsn == "postgresql+asyncpg://u:p@h:5432/d"


def test_config_deepseek_defaults():
    from app.core.config import Settings
    s = Settings()
    assert s.deepseek_api_base == "https://api.deepseek.com"
    assert s.deepseek_main_model == "deepseek-v4-flash"
    assert s.deepseek_wiki_model == "deepseek-v4-pro"


def test_config_mineru_defaults():
    from app.core.config import Settings
    s = Settings()
    assert s.mineru_api_base == "https://mineru.net/api/v4"
    assert s.mineru_model_version == "vlm"
    assert s.mineru_language == "ch"


def test_password_hash_and_verify():
    from app.core.security import hash_password, verify_password
    h = hash_password("hello123")
    assert h != "hello123"
    assert verify_password("hello123", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    from app.core.security import create_access_token, decode_token
    token = create_access_token(42, extra={"role": "admin"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"
    assert "iat" in payload and "exp" in payload


def test_jwt_invalid_token_raises():
    from app.core.security import decode_token
    with pytest.raises(ValueError):
        decode_token("not.a.valid.jwt")


def test_user_schema_validation():
    from app.schemas.auth import UserCreate
    u = UserCreate(username="alice", password="secret123")
    assert u.username == "alice"
    with pytest.raises(Exception):
        UserCreate(username="bob", password="123")
    with pytest.raises(Exception):
        UserCreate(username="ab", password="secret123")


@pytest.mark.asyncio
async def test_llm_mock_chat_stream():
    from app.services.llm.deepseek_client import LLMMockClient
    client = LLMMockClient()
    chunks = []
    async for c in client.chat_stream([{"role": "user", "content": "你好"}]):
        chunks.append(c)
    text = "".join(chunks)
    assert "[MOCK LLM]" in text
    assert "你好" in text


@pytest.mark.asyncio
async def test_llm_mock_generate():
    from app.services.llm.deepseek_client import LLMMockClient
    client = LLMMockClient()
    out = await client.generate("测试 prompt")
    assert "[MOCK LLM]" in out
    assert "测试 prompt" in out


@pytest.mark.asyncio
async def test_llm_factory_returns_mock_when_no_key():
    from app.services.llm import deepseek_client as ds
    ds._client = None
    client = ds.get_llm_client()
    assert isinstance(client, ds.LLMMockClient)


@pytest.mark.asyncio
async def test_mineru_mock_parse_md():
    from app.services.ingestion.mineru_client import MinerUMockClient, MarkdownResult
    client = MinerUMockClient()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# 标题\n\n正文内容")
        path = f.name
    try:
        result = await client.parse(path)
        assert isinstance(result, MarkdownResult)
        assert "正文内容" in result.markdown
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_mineru_mock_parse_pdf_returns_placeholder():
    from app.services.ingestion.mineru_client import MinerUMockClient
    client = MinerUMockClient()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake pdf bytes")
        path = f.name
    try:
        result = await client.parse(path)
        assert "[MOCK MinerU]" in result.markdown
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_mineru_real_client_parse_md_shortcut():
    """真实 client 对 .md 文件应直接读取，不走 API（节省配额）"""
    from app.services.ingestion.mineru_client import MinerURealClient, MarkdownResult
    client = MinerURealClient()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# 直接读取的 markdown\n\n内容")
        path = f.name
    try:
        result = await client.parse(path)
        assert "直接读取的 markdown" in result.markdown
        assert isinstance(result, MarkdownResult)
    finally:
        os.unlink(path)


def test_milvus_init_script_importable():
    import py_compile
    init_path = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "init_milvus.py"
    assert py_compile.compile(str(init_path), doraise=True)
