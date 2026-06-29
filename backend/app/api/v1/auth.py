"""鉴权接口：注册 / 登录 / 当前用户"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import TokenOut, UserCreate, UserLogin, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_session)):
    stmt = select(User).where(User.username == payload.username)
    if (await db.execute(stmt)).scalar_one_or_none():
        raise HTTPException(400, detail="用户名已存在")

    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role="user",
    )
    # 第一个用户自动成为 admin
    count_stmt = select(User)
    if (await db.execute(count_stmt)).first() is None:
        user.role = "admin"

    db.add(user)
    await db.flush()
    token = create_access_token(user.id, extra={"role": user.role})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_session)):
    stmt = select(User).where(User.username == payload.username)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(403, detail="账号已停用")

    token = create_access_token(user.id, extra={"role": user.role})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return user
