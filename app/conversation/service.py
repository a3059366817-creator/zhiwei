"""会话与消息的数据访问 + 业务逻辑。

规格要求：业务逻辑不直接写 SQL，统一走这里。
"""

from __future__ import annotations

import logging

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Conversation, Message, User

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 16


async def get_active_conversation(session: AsyncSession, user: User) -> Conversation:
    """取当前活跃会话，没有就建一个。"""
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.status == "active")
        .order_by(desc(Conversation.updated_at))
        .limit(1)
    )
    conv = await session.scalar(stmt)
    if conv is None:
        conv = Conversation(user_id=user.id, title=None, status="active")
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        logger.info("新建会话 %s", conv.id)
    return conv


async def start_new_conversation(session: AsyncSession, user: User) -> Conversation:
    """归档旧会话，开一个新的。"""
    old = await session.scalars(
        select(Conversation).where(
            Conversation.user_id == user.id, Conversation.status == "active"
        )
    )
    for c in old:
        c.status = "archived"
    conv = Conversation(user_id=user.id, title=None, status="active")
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    logger.info("开启新会话 %s", conv.id)
    return conv


async def add_message(
    session: AsyncSession,
    conversation: Conversation,
    role: str,
    content: str,
    model_name: str | None = None,
) -> Message:
    msg = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        model_name=model_name,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def recent_messages(
    session: AsyncSession, conversation_id: str, limit: int = HISTORY_LIMIT
) -> list[dict]:
    """返回按时间正序的最近 N 条消息（直接可用作模型上下文）。"""
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(limit)
    )
    items = list(rows)[::-1]
    allowed = {"user", "assistant"}
    return [{"role": m.role, "content": m.content} for m in items if m.role in allowed]


async def list_conversations(
    session: AsyncSession, user_id: str, limit: int = 10
) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(desc(Conversation.updated_at))
        .limit(limit)
    )
    return list(rows)


async def message_count(session: AsyncSession, conversation_id: str) -> int:
    from sqlalchemy import func

    stmt = (
        select(func.count())
        .select_from(Message)
        .where(Message.conversation_id == conversation_id)
    )
    return (await session.scalar(stmt)) or 0
