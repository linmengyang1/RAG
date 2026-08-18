"""应用配置：单例 Settings，pydantic-settings 自动读取 .env"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ───── 应用 ─────
    app_env: str = "development"
    app_name: str = "Graduate RAG"
    app_log_level: str = "INFO"
    app_cors_origins: List[str] = ["http://localhost:3000"]

    # ───── PostgreSQL ─────
    postgres_user: str = "grad"
    postgres_password: str = "grad123"
    postgres_db: str = "grad_rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # ───── Milvus ─────
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_chunks: str = "chunks"
    milvus_collection_wiki: str = "wiki"

    # ───── MinIO ─────
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "grad-rag"

    # ───── 数据路径 ─────
    data_output_dir: str = "/data/output"
    mineru_cache_dir: str = "/data/mineru_cache"

    # ───── DeepSeek LLM ─────
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    deepseek_main_model: str = "deepseek-v4-flash"   # 主力（RAG 问答）
    deepseek_wiki_model: str = "deepseek-v4-flash"     # Wiki 生成
    llm_use_mock: bool = False

    # ───── MinerU ─────
    mineru_api_token: str = ""
    mineru_api_base: str = "https://mineru.net/api/v4"
    mineru_model_version: str = "vlm"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    mineru_language: str = "ch"
    mineru_timeout: int = 600          # 单文件解析超时（秒）
    mineru_poll_interval: int = 5      # 轮询间隔（秒）
    mineru_use_mock: bool = False

    # ───── 本地模型 ─────
    embed_model: str = "BAAI/bge-m3"
    embed_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    torch_device: str = "cuda"
    embed_lazy_load: bool = True
    reranker_lazy_load: bool = True

    # ───── RAG 检索策略 ─────
    # 为 True 时，统计类查询（如"各学院导师数量"）走 hybrid_search 检索 chunks
    # 而非 SQL 聚合 mentors 表。用于 RAGAS 评测等场景，让统计答案也经过完整 RAG 管线
    stats_use_rag: bool = False

    # ───── JWT ─────
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_alg: str = "HS256"
    jwt_exp_minutes: int = 10080  # 7 天
    auth_disabled: bool = False

    @field_validator("app_cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # ───── 派生属性 ─────
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def llm_should_use_mock(self) -> bool:
        """未配置 API key 时强制走 mock"""
        return self.llm_use_mock or not self.deepseek_api_key

    @property
    def mineru_should_use_mock(self) -> bool:
        return self.mineru_use_mock or not self.mineru_api_token

    @property
    def is_dev(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
