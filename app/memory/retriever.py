"""记忆检索：先做关键词 + 重要度 + 时间衰减，够用且可解释。

后续记忆量上来再换 pgvector 语义检索（规格 3.6）。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Memory

STOPWORDS = {
    "的",
    "了",
    "是",
    "我",
    "你",
    "他",
    "她",
    "在",
    "有",
    "和",
    "就",
    "都",
    "也",
    "很",
    "这个",
    "那个",
    "什么",
    "怎么",
    "今天",
    "现在",
    "但是",
    "因为",
    "所以",
    "然后",
    "还是",
    "可以",
    "一下",
}

_LATIN = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.-]{1,}")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


def keywords(text: str) -> set[str]:
    """中英混合的粗粒度分词：英文词 + 中文二元组。"""
    out: set[str] = set()
    for w in _LATIN.findall(text):
        out.add(w.lower())
    for block in _CJK.findall(text):
        if len(block) == 1:
            continue
        for i in range(len(block) - 1):
            bg = block[i : i + 2]
            if bg not in STOPWORDS:
                out.add(bg)
    return out


def _recency_bonus(updated: datetime | None, now: datetime) -> float:
    if updated is None:
        return 0.0
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    days = max((now - updated).days, 0)
    return max(0.0, 1.0 - days / 180.0)


async def retrieve(
    session: AsyncSession, user_id: str, query: str, limit: int = 6
) -> list[str]:
    """返回与当前消息最相关的若干条记忆内容。"""
    q = keywords(query)
    if not q:
        return []

    now = datetime.now(UTC)
    rows = await session.scalars(
        select(Memory).where(Memory.user_id == user_id, Memory.status == "active").limit(500)
    )

    scored: list[tuple[float, str]] = []
    for m in rows:
        if m.expires_at is not None:
            exp = m.expires_at if m.expires_at.tzinfo else m.expires_at.replace(tzinfo=UTC)
            if exp < now:
                continue
        mq = keywords(m.content)
        overlap = len(q & mq)
        if overlap == 0:
            continue
        score = overlap * 2.0 + m.importance * 0.3 + _recency_bonus(m.updated_at, now)
        scored.append((score, m.content))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [content for _score, content in scored[:limit]]
