"""提醒的增删改查与到期判定。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Reminder, User

logger = logging.getLogger(__name__)


def _as_utc(dt: datetime) -> datetime:
    """SQLite 取回来的 TIMESTAMPTZ 是 naive，统一按 UTC 解释。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def to_utc(local_naive: datetime, timezone: str) -> datetime:
    """把「用户本地墙上时间」转成 UTC。模型输出的都是本地时间，服务器跑在 UTC。"""
    tz = ZoneInfo(timezone)
    return local_naive.replace(tzinfo=tz).astimezone(UTC)


def to_local(dt: datetime, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def fmt_local(dt: datetime | None, timezone: str) -> str:
    if dt is None:
        return "未设时间"
    local = to_local(dt, timezone)
    return local.strftime("%m月%d日 %H:%M")


async def create_reminder(
    session: AsyncSession,
    user: User,
    title: str,
    due_at: datetime | None = None,
    *,
    source: str = "chat",
    notes: str | None = None,
) -> Reminder:
    title = title.strip()[:200]

    # 去重：同一件事一分钟内被重复要求（模型多轮重复打标签、或消息重投）只保留一条
    if due_at is not None:
        window_start = due_at - timedelta(seconds=60)
        window_end = due_at + timedelta(seconds=60)
        dup = await session.scalar(
            select(Reminder).where(
                Reminder.user_id == user.id,
                Reminder.status == "pending",
                Reminder.title == title,
                Reminder.due_at.is_not(None),
                Reminder.due_at >= window_start,
                Reminder.due_at <= window_end,
            )
        )
        if dup is not None:
            logger.info("重复提醒已忽略：%s", title)
            return dup

    row = Reminder(
        user_id=user.id,
        title=title,
        notes=notes,
        due_at=due_at,
        status="pending",
        source=source,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("新建提醒：%s @ %s", row.title, row.due_at)
    return row


async def list_pending(session: AsyncSession, user_id: str, limit: int = 30) -> list[Reminder]:
    rows = await session.scalars(
        select(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == "pending")
        .order_by(Reminder.due_at.is_(None), Reminder.due_at, Reminder.created_at)
        .limit(limit)
    )
    return list(rows)


async def get_reminder(session: AsyncSession, user_id: str, rid: str) -> Reminder | None:
    return await session.scalar(
        select(Reminder).where(Reminder.id == rid, Reminder.user_id == user_id)
    )


async def find_by_keyword(session: AsyncSession, user_id: str, kw: str) -> Reminder | None:
    return await session.scalar(
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.status == "pending",
            Reminder.title.like(f"%{kw}%"),
        )
        .order_by(Reminder.due_at.is_(None), Reminder.due_at)
        .limit(1)
    )


async def complete(session: AsyncSession, user_id: str, rid: str) -> Reminder | None:
    row = await get_reminder(session, user_id, rid)
    if row is None:
        return None
    row.status = "done"
    row.done_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row


async def cancel(session: AsyncSession, user_id: str, rid: str) -> Reminder | None:
    row = await get_reminder(session, user_id, rid)
    if row is None:
        return None
    row.status = "cancelled"
    await session.commit()
    await session.refresh(row)
    return row


async def snooze(
    session: AsyncSession, user_id: str, rid: str, minutes: int = 20
) -> Reminder | None:
    row = await get_reminder(session, user_id, rid)
    if row is None:
        return None
    now = datetime.now(UTC)
    base = max(_as_utc(row.due_at) if row.due_at else now, now)
    row.due_at = base + timedelta(minutes=minutes)
    row.last_remind_at = None
    await session.commit()
    await session.refresh(row)
    return row


async def due_for_nudge(
    session: AsyncSession,
    now: datetime,
    *,
    max_nudges: int = 3,
    gap_minutes: int = 20,
) -> list[Reminder]:
    """到点且还没追够次数的提醒。"""
    gap_before = now - timedelta(minutes=gap_minutes)
    rows = await session.scalars(
        select(Reminder)
        .where(
            Reminder.status == "pending",
            Reminder.due_at.is_not(None),
            Reminder.due_at <= now,
            Reminder.remind_count < max_nudges,
        )
        .order_by(Reminder.due_at)
    )
    out = []
    for r in rows:
        last = r.last_remind_at
        if last is not None and _as_utc(last) > gap_before:
            continue
        out.append(r)
    return out


async def mark_reminded(session: AsyncSession, row: Reminder) -> None:
    row.remind_count += 1
    row.last_remind_at = datetime.now(UTC)
    await session.commit()


async def upcoming(session: AsyncSession, user_id: str, limit: int = 10) -> list[Reminder]:
    rows = await session.scalars(
        select(Reminder)
        .where(
            Reminder.user_id == user_id,
            Reminder.status == "pending",
            Reminder.due_at.is_not(None),
        )
        .order_by(Reminder.due_at)
        .limit(limit)
    )
    return list(rows)


async def recent_done(session: AsyncSession, user_id: str, limit: int = 5) -> list[Reminder]:
    rows = await session.scalars(
        select(Reminder)
        .where(Reminder.user_id == user_id, Reminder.status == "done")
        .order_by(desc(Reminder.done_at))
        .limit(limit)
    )
    return list(rows)
