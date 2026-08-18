"""FastAPI 应用入口"""
from __future__ import annotations

import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import logger, setup_logging

# infra/scripts/init_milvus.py 在容器内挂载路径（docker-compose.yml: ./infra:/app/infra:ro）
# 宿主机开发时用相对路径回退
_INIT_MILVUS_SCRIPT = Path("/app/infra/scripts/init_milvus.py")
if not _INIT_MILVUS_SCRIPT.exists():
    _INIT_MILVUS_SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "scripts" / "init_milvus.py"


def _ensure_milvus_collections() -> None:
    """幂等初始化 Milvus collection：若不存在则创建，已存在则跳过。

    复用 infra/scripts/init_milvus.py 的幂等逻辑（has_collection 检查 + 不带 --force 不重建），
    避免 backend 容器 down/up 重启后 chunks/wiki collection 丢失导致 collection not found。
    """
    if not _INIT_MILVUS_SCRIPT.exists():
        logger.warning(f"Milvus 初始化脚本不存在: {_INIT_MILVUS_SCRIPT}，跳过自动初始化")
        return
    try:
        # init_milvus.py 内部有 60s 等 Milvus 就绪 + 幂等创建 + load_collection 逻辑
        result = subprocess.run(
            ["python", str(_INIT_MILVUS_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            # 只记最后一行关键信息，避免日志过长
            last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "OK"
            logger.info(f"Milvus collection 初始化完成: {last_line}")
        else:
            logger.error(f"Milvus collection 初始化失败: {result.stderr[-300:]}")
    except subprocess.TimeoutExpired:
        logger.error("Milvus collection 初始化超时（180s），跳过")
    except Exception as e:
        logger.error(f"Milvus collection 初始化异常: {e}")


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

    # 幂等初始化 Milvus collection（不存在才创建，已存在跳过）
    # 让 Milvus 像 PostgreSQL（init_postgres.sql）一样在容器启动时自动建表
    _ensure_milvus_collections()

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
