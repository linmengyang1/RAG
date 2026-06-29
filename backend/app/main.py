"""FastAPI 应用入口"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"启动 {settings.app_name} (env={settings.app_env})")
    # 健康组件探针：延迟导入避免循环
    from app.db.session import check_db_connection
    try:
        ok = await check_db_connection()
        logger.info(f"PostgreSQL 连接: {'OK' if ok else 'FAIL'}")
    except Exception as e:
        logger.error(f"PostgreSQL 连接失败: {e}")

    yield
    logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="研究生院知识库 RAG 后端",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """健康检查"""
    from sqlalchemy import text
    from app.db.session import engine

    db_ok = False
    milvus_ok = False
    try:
        async with engine.connect() as conn:
            db_ok = (await conn.execute(text("SELECT 1"))).scalar() == 1
    except Exception as e:
        logger.debug(f"health: DB 探测失败 {e}")

    try:
        from pymilvus import MilvusClient
        client = MilvusClient(uri=settings.milvus_uri)
        milvus_ok = len(client.list_collections()) >= 0
    except Exception as e:
        logger.debug(f"health: Milvus 探测失败 {e}")

    status = "ok" if (db_ok and milvus_ok) else "degraded"
    return {
        "status": status,
        "service": settings.app_name,
        "env": settings.app_env,
        "postgres": "ok" if db_ok else "down",
        "milvus": "ok" if milvus_ok else "down",
        "llm_mock": settings.llm_should_use_mock,
        "mineru_mock": settings.mineru_should_use_mock,
        "auth_disabled": settings.auth_disabled,
    }


@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }
