"""FastAPI 依赖注入：当前用户、DB session"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_session
from app.models.user import User


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
) -> User:
    """从 Authorization: Bearer <token> 解析当前用户。

    若 settings.auth_disabled=True，则返回一个虚拟管理员用户（仅本地内网用）。
    """
    if settings.auth_disabled:
        # 直接返回 admin（不存在则 lazy 创建）
        stmt = select(User).where(User.username == "admin")
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            from app.core.security import hash_password
            user = User(
                username="admin",
                password_hash=hash_password("admin"),
                role="admin",
            )
            db.add(user)
            await db.flush()
        return user

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 格式应为 'Bearer <token>'",
        )
    try:
        payload = decode_token(parts[1])
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="token 中无 sub")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """仅 admin 角色可访问"""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要 admin 权限")
    return user


__all__ = ["get_current_user", "get_current_admin"]
