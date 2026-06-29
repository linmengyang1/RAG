"""日志：loguru 统一配置"""
from __future__ import annotations

import sys

from loguru import logger

from app.core.config import settings


def setup_logging() -> None:
    logger.remove()
    level = settings.app_log_level.upper()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(sys.stderr, level=level, format=fmt, colorize=True)
    if settings.is_dev:
        logger.add("logs/app.log", rotation="50 MB", retention=10, level="DEBUG")
    logger.info(f"日志初始化完成 (level={level}, env={settings.app_env})")


__all__ = ["logger", "setup_logging"]
