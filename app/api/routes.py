"""HTTP 接口：V1.0 只保留最小集合（规格第七部分）。

Telegram 是主要入口，这里主要给部署平台做健康检查和后续扩展用。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.connection import get_session, ping_db
from app.database.models import Memory, User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
async def root() -> dict:
    settings = get_settings()
    return {
        "name": f"{settings.ai_name} ZhiWei",
        "version": "0.1.0",
        "description": "私人 Telegram AI 伙伴",
        "env": settings.app_env,
        "docs": "/docs",
    }


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    settings = get_settings()
    db_ok = await ping_db()
    stats: dict[str, int] = {}
    if db_ok:
        try:
            stats["users"] = (await session.scalar(select(func.count()).select_from(User))) or 0
            stats["memories"] = (
                await session.scalar(select(func.count()).select_from(Memory))
            ) or 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("统计查询失败：%s", type(exc).__name__)
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "config": settings.public_dict(),
        "stats": stats,
    }
