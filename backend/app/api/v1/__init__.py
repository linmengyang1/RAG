"""API v1 路由聚合"""
from fastapi import APIRouter

from app.api.v1 import auth, chat, search, wiki

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(search.router)
api_router.include_router(chat.router)
api_router.include_router(wiki.router)
