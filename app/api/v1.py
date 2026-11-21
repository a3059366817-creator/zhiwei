"""只读 HTTP 接口（规格第七部分）。

数据类接口必须鉴权：这里用 `ADMIN_API_TOKEN`（请求头 X-API-Token 或 Bearer）。
没配置令牌时，所有数据接口一律 401，保证默认不暴露隐私。
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation import service as conv_service
from app.core.config import get_settings
from app.database.connection import get_session
from app.memory import manager
from app.people import service as people_service
from app.profile.service import build_profile
from app.services import user_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


async def require_token(
    x_api_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().admin_api_token
    if not expected:
        raise HTTPException(status_code=401, detail="api access disabled")
    provided = x_api_token or ""
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid token")


async def _owner(session: AsyncSession):
    settings = get_settings()
    if settings.telegram_user_id is None:
        raise HTTPException(status_code=404, detail="no owner configured")
    user = await user_service.get_by_telegram_id(session, settings.telegram_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="owner not found")
    return user


@router.get("/models", dependencies=[Depends(require_token)])
async def list_models() -> dict:
    settings = get_settings()
    return {
        "primary": settings.llm_provider,
        "fallback": settings.llm_fallback_provider or None,
        "ollama_model": settings.ollama_model,
        "gemini_model": settings.gemini_model,
        "openrouter_model": settings.openrouter_model or None,
        "deepseek_model": settings.deepseek_model,
    }


@router.get("/memories", dependencies=[Depends(require_token)])
async def list_memories(
    category: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await _owner(session)
    rows = await manager.list_memories(session, user.id, category=category, limit=limit)
    return {
        "count": len(rows),
        "items": [
            {
                "id": m.id,
                "category": m.category,
                "content": m.content,
                "importance": m.importance,
                "source_message_id": m.source_message_id,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in rows
        ],
    }


@router.get("/profile", dependencies=[Depends(require_token)])
async def get_profile(session: AsyncSession = Depends(get_session)) -> dict:
    user = await _owner(session)
    grouped = await build_profile(session, user)
    return {"user": user.display_name, "sections": grouped}


@router.get("/conversations", dependencies=[Depends(require_token)])
async def list_conversations(
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await _owner(session)
    rows = await conv_service.list_conversations(session, user.id, limit=limit)
    return {
        "count": len(rows),
        "items": [
            {
                "id": c.id,
                "status": c.status,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "messages": await conv_service.message_count(session, c.id),
            }
            for c in rows
        ],
    }


@router.post("/internal/tick", dependencies=[Depends(require_token)])
async def internal_tick(request: Request) -> dict:
    """外部 cron 调用：唤醒服务并立刻检查一次到期提醒。

    Render 免费实例会休眠，进程内定时器在休眠期间不跑，
    所以需要外部每几分钟打一次这个接口（GitHub Actions 已配好）。
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return {"sent": 0, "reason": "scheduler not running"}
    sent = await scheduler.tick()
    return {"sent": sent}


@router.get("/people", dependencies=[Depends(require_token)])
async def list_people(session: AsyncSession = Depends(get_session)) -> dict:
    user = await _owner(session)
    rows = await people_service.list_people(session, user.id)
    return {
        "count": len(rows),
        "items": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "relations": [
                    {"type": r.relation_type, "description": r.description} for r in rels
                ],
            }
            for p, rels in rows
        ],
    }
