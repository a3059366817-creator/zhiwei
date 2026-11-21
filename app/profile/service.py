"""个人画像：把已确认的记忆按维度聚合，供 /profile 查看与对话注入。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.memory import manager

logger = logging.getLogger(__name__)

# 画像的分区：类别 -> 标题
SECTIONS: list[tuple[str, str]] = [
    ("profile", "身份与技能"),
    ("preference", "偏好"),
    ("experience", "经历与项目"),
    ("context", "近期状态"),
]


async def build_profile(session: AsyncSession, user: User) -> dict[str, list[str]]:
    rows = await manager.list_memories(session, user.id, limit=200)
    grouped: dict[str, list[str]] = {key: [] for key, _ in SECTIONS}
    for m in rows:
        grouped.setdefault(m.category, []).append(m.content)
    return grouped


async def profile_summary_lines(session: AsyncSession, user: User, limit: int = 12) -> list[str]:
    """给对话上下文用的精简画像（只取高价值的几条）。"""
    grouped = await build_profile(session, user)
    lines: list[str] = []
    for key, title in SECTIONS:
        items = grouped.get(key, [])
        if not items:
            continue
        lines.append(f"{title}：{'；'.join(items[:3])}")
        if len(lines) >= limit:
            break
    return lines


def render_profile_text(user_name: str, grouped: dict[str, list[str]]) -> str:
    total = sum(len(v) for v in grouped.values())
    if total == 0:
        return "我还什么都没记住。多跟我说说你自己，我会慢慢建立你的画像。"

    lines = [f"{user_name}，我现在对你的了解："]
    for key, title in SECTIONS:
        items = grouped.get(key, [])
        if not items:
            continue
        lines.append("")
        lines.append(f"【{title}】")
        for it in items[:10]:
            lines.append(f"· {it}")

    shown = sum(len(grouped.get(key, [])) for key, _ in SECTIONS)
    others = total - shown
    if others > 0:
        lines.append("")
        lines.append(f"（另有 {others} 条人物关系，用 /people 查看）")

    lines.append("")
    lines.append(f"（共 {total} 条，全部来自你确认过的记忆。用 /memory 可以删。）")
    return "\n".join(lines)
