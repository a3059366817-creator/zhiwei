"""中间件：访问控制 + 每个更新一个数据库会话。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.core.config import Settings
from app.database.connection import get_session_factory

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """只允许配置里那一个 Telegram 用户使用（规格 8.1）。"""

    def __init__(self, settings: Settings) -> None:
        self.owner_id = settings.telegram_user_id
        self._warned: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if self.owner_id is None:
            logger.warning("TELEGRAM_USER_ID 未配置，拒绝所有消息")
            return None
        if user is None or user.id != self.owner_id:
            uid = getattr(user, "id", None)
            logger.warning("拒绝未授权用户：%s", uid)
            if isinstance(event, Update) and event.message and uid not in self._warned:
                self._warned.add(uid)  # 只提示一次，避免被刷
                try:
                    await event.message.answer("这是私人的助手，不对外的。")
                except Exception:  # noqa: BLE001
                    pass
            return None
        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    """每个更新开一个会话，正常提交、异常回滚。"""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with get_session_factory()() as session:
            data["session"] = session
            try:
                return await handler(event, data)
            except Exception:
                await session.rollback()
                raise
