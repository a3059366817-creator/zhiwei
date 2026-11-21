"""记忆库管理：候选的创建/确认/拒绝，正式记忆的增删改查。

规格 8.3：删除必须真正删除持久化记录，并处理关联引用。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Memory, MemoryCandidate, User
from app.memory.schemas import (
    Decision,
    ExtractedCandidate,
    MemoryCategory,
    ReviewResult,
    Sensitivity,
)

logger = logging.getLogger(__name__)

DEFAULT_IMPORTANCE = {
    MemoryCategory.PROFILE: 4,
    MemoryCategory.PREFERENCE: 4,
    MemoryCategory.EXPERIENCE: 5,
    MemoryCategory.RELATIONSHIP: 5,
    MemoryCategory.CONTEXT: 2,
}


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text)


def _bigrams(text: str) -> set[str]:
    t = _normalize(text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def similar(a: str, b: str) -> float:
    """包含式相似度：短句被长句覆盖也算重复。"""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / min(len(ga), len(gb))


async def find_similar_memory(
    session: AsyncSession, user_id: str, content: str, threshold: float = 0.62
) -> Memory | None:
    rows = await session.scalars(
        select(Memory)
        .where(Memory.user_id == user_id, Memory.status == "active")
        .order_by(desc(Memory.created_at))
        .limit(300)
    )
    for m in rows:
        if similar(content, m.content) >= threshold:
            return m
    return None


async def save_memory(
    session: AsyncSession,
    user: User,
    *,
    category: str,
    content: str,
    source_message_id: str | None = None,
    importance: int | None = None,
    expires_at: datetime | None = None,
) -> tuple[Memory, bool]:
    """写入正式记忆。返回 (记录, 是否新建)。相同内容会合并而不是重复插入。"""
    existing = await find_similar_memory(session, user.id, content)
    if existing is not None:
        existing.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(existing)
        return existing, False

    memory = Memory(
        user_id=user.id,
        category=category,
        content=content,
        importance=importance or DEFAULT_IMPORTANCE.get(MemoryCategory(category), 3),
        source_message_id=source_message_id,
        status="active",
        expires_at=expires_at,
    )
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory, True


async def create_candidate(
    session: AsyncSession,
    user: User,
    candidate: ExtractedCandidate,
    review: ReviewResult,
    source_message_id: str | None = None,
) -> MemoryCandidate:
    row = MemoryCandidate(
        user_id=user.id,
        category=candidate.category.value,
        content=candidate.content,
        reason=candidate.reason or review.reason,
        source_message_id=source_message_id,
        sensitivity_level=review.sensitivity.value,
        person_name=candidate.person_name,
        relation_type=candidate.relation_type,
        status="pending",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def get_candidate(session: AsyncSession, candidate_id: str) -> MemoryCandidate | None:
    return await session.scalar(
        select(MemoryCandidate).where(MemoryCandidate.id == candidate_id)
    )


async def approve_candidate(session: AsyncSession, candidate: MemoryCandidate) -> Memory:
    """确认后写入正式记忆；人物关系同时归档到 people / relationships。"""
    user = await session.get(User, candidate.user_id)
    if user is None:
        raise ValueError("候选对应的用户不存在")
    memory, _new = await save_memory(
        session,
        user,
        category=candidate.category,
        content=candidate.content,
        source_message_id=candidate.source_message_id,
    )

    if candidate.category == MemoryCategory.RELATIONSHIP.value and candidate.person_name:
        # 延迟导入，避免模块级循环依赖
        from app.people import service as people_service

        person = await people_service.upsert_person(
            session, user, candidate.person_name, description=candidate.content
        )
        await people_service.add_relationship(
            session,
            user,
            person,
            relation_type=candidate.relation_type or "未明确",
            description=candidate.content,
            source_message_id=candidate.source_message_id,
        )

    candidate.status = "approved"
    candidate.reviewed_at = datetime.now(UTC)
    await session.commit()
    logger.info("记忆候选已确认：%s", candidate.id)
    return memory


async def reject_candidate(session: AsyncSession, candidate: MemoryCandidate) -> None:
    candidate.status = "rejected"
    candidate.reviewed_at = datetime.now(UTC)
    await session.commit()


async def never_ask_candidate(session: AsyncSession, candidate: MemoryCandidate) -> None:
    candidate.status = "never_ask"
    candidate.reviewed_at = datetime.now(UTC)
    await session.commit()


async def pending_candidates(
    session: AsyncSession, user_id: str, limit: int = 10
) -> list[MemoryCandidate]:
    rows = await session.scalars(
        select(MemoryCandidate)
        .where(MemoryCandidate.user_id == user_id, MemoryCandidate.status == "pending")
        .order_by(desc(MemoryCandidate.created_at))
        .limit(limit)
    )
    return list(rows)


async def list_memories(
    session: AsyncSession, user_id: str, category: str | None = None, limit: int = 30
) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id, Memory.status == "active")
    if category:
        stmt = stmt.where(Memory.category == category)
    stmt = stmt.order_by(desc(Memory.importance), desc(Memory.updated_at)).limit(limit)
    return list(await session.scalars(stmt))


async def get_memory(session: AsyncSession, user_id: str, memory_id: str) -> Memory | None:
    return await session.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    )


async def delete_memory(session: AsyncSession, user_id: str, memory_id: str) -> bool:
    """真删除（不是标记删除）。"""
    memory = await get_memory(session, user_id, memory_id)
    if memory is None:
        return False
    await session.execute(delete(Memory).where(Memory.id == memory_id))
    await session.commit()
    logger.info("记忆已删除：%s", memory_id)
    return True


async def update_memory(
    session: AsyncSession, user_id: str, memory_id: str, content: str
) -> Memory | None:
    memory = await get_memory(session, user_id, memory_id)
    if memory is None:
        return None
    memory.content = content.strip()
    memory.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(memory)
    return memory


async def apply_auto_save(
    session: AsyncSession,
    user: User,
    candidate: ExtractedCandidate,
    review: ReviewResult,
    source_message_id: str | None = None,
) -> tuple[Memory, bool]:
    assert review.decision == Decision.AUTO_SAVE
    expires = None
    if candidate.category == MemoryCategory.CONTEXT:
        # 情境记忆默认 14 天后过期（规格：情境记忆应支持过期/更新/归档）
        from datetime import timedelta

        expires = datetime.now(UTC) + timedelta(days=14)
    return await save_memory(
        session,
        user,
        category=candidate.category.value,
        content=candidate.content,
        source_message_id=source_message_id,
        expires_at=expires,
    )


__all__ = [
    "Sensitivity",
    "apply_auto_save",
    "approve_candidate",
    "create_candidate",
    "delete_memory",
    "get_candidate",
    "get_memory",
    "list_memories",
    "never_ask_candidate",
    "pending_candidates",
    "reject_candidate",
    "save_memory",
    "update_memory",
]
