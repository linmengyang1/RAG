"""会话管理 API

端点：
    GET  /api/v1/conversations        列出当前用户的会话（分页）
    GET  /api/v1/conversations/{id}    查看会话消息列表
    PATCH /api/v1/conversations/{id}  重命名会话
    DELETE /api/v1/conversations/{id} 删除会话
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.logging import logger
from app.db.session import get_session
from app.models.conversation import Conversation, Message
from app.models.user import User

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationItem(BaseModel):
    """会话列表项"""
    id: int
    title: str | None = None
    message_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ConversationListResponse(BaseModel):
    """会话列表响应"""
    items: list[ConversationItem]
    total: int


class ConversationDetail(BaseModel):
    """会话详情（含消息列表）"""
    id: int
    title: str | None = None
    messages: list["MessageItem"]


class MessageItem(BaseModel):
    """消息项"""
    id: int
    role: str
    content: str
    created_at: str | None = None


class RenameRequest(BaseModel):
    """重命名请求"""
    title: str = Field(..., min_length=1, max_length=255)


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """列出当前用户的会话（按更新时间倒序）"""
    # 总数
    count_stmt = (
        select(func.count(Conversation.id))
        .where(Conversation.user_id == user.id)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页查询
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    items = []
    for conv in conversations:
        # 查询消息数量
        msg_count_stmt = (
            select(func.count(Message.id))
            .where(Message.conversation_id == conv.id)
        )
        msg_count = (await db.execute(msg_count_stmt)).scalar_one()

        items.append(ConversationItem(
            id=conv.id,
            title=conv.title,
            message_count=msg_count,
            created_at=conv.created_at.isoformat() if conv.created_at else None,
            updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
        ))

    return ConversationListResponse(items=items, total=total)


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """查看会话消息列表"""
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    # 查询消息
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.id)
    )
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        messages=[
            MessageItem(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in messages
        ],
    )


@router.patch("/{conv_id}", response_model=ConversationItem)
async def rename_conversation(
    conv_id: int,
    req: RenameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """重命名会话"""
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    conv.title = req.title
    await db.flush()

    # 查询消息数量
    msg_count_stmt = (
        select(func.count(Message.id))
        .where(Message.conversation_id == conv.id)
    )
    msg_count = (await db.execute(msg_count_stmt)).scalar_one()

    logger.info(f"会话重命名: id={conv.id}, title={req.title!r}")
    return ConversationItem(
        id=conv.id,
        title=conv.title,
        message_count=msg_count,
        created_at=conv.created_at.isoformat() if conv.created_at else None,
        updated_at=conv.updated_at.isoformat() if conv.updated_at else None,
    )


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """删除会话（CASCADE 关联消息）"""
    conv = await db.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    await db.delete(conv)
    logger.info(f"会话已删除: id={conv_id}, title={conv.title!r}")
    return {"detail": "ok"}
