"""用户与用户设置。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserSettings

logger = logging.getLogger(__name__)


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def get_or_create(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    display_name: str | None = None,
) -> User:
    user = await get_by_telegram_id(session, telegram_id)
    if user is None:
        user = User(telegram_id=telegram_id, username=username, display_name=display_name)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("新用户登记：telegram_id=%s", telegram_id)
    else:
        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed = True
        if changed:
            await session.commit()
    return user


async def get_settings_row(session: AsyncSession, user: User) -> UserSettings:
    row = await session.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if row is None:
        row = UserSettings(user_id=user.id)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def update_settings(
    session: AsyncSession,
    user: User,
    *,
    model_provider: str | None = None,
    model_name: str | None = None,
    memory_enabled: bool | None = None,
    auto_save_enabled: bool | None = None,
) -> UserSettings:
    row = await get_settings_row(session, user)
    if model_provider is not None:
        row.model_provider = model_provider
    if model_name is not None:
        row.model_name = model_name
    if memory_enabled is not None:
        row.memory_enabled = memory_enabled
    if auto_save_enabled is not None:
        row.auto_save_enabled = auto_save_enabled
    await session.commit()
    await session.refresh(row)
    return row
