"""记忆流水线：提取 → 审核 → 自动保存 / 请求确认。

设计要点（规格关键决策 3）：模型只负责「提出」，是否入库完全由这里和 rules.py 决定。
"""

from __future__ import annotations

import logging

from aiogram import Bot

from app.bot.keyboards import memory_candidate
from app.core.config import Settings
from app.database.connection import get_session_factory
from app.llm.router import LLMRouter
from app.memory import manager
from app.memory.extractor import MemoryExtractor
from app.memory.rules import review as review_candidate
from app.memory.schemas import Decision, MemoryCategory
from app.services import user_service

logger = logging.getLogger(__name__)

CATEGORY_LABEL = {
    MemoryCategory.PROFILE: "身份 / 兴趣",
    MemoryCategory.EXPERIENCE: "经历 / 项目",
    MemoryCategory.RELATIONSHIP: "人物关系",
    MemoryCategory.CONTEXT: "近期状态",
    MemoryCategory.PREFERENCE: "偏好",
}


def _confirm_text(settings: Settings, candidate) -> str:
    label = CATEGORY_LABEL.get(MemoryCategory(candidate.category), candidate.category)
    lines = [
        f"{settings.user_name}，刚才这件事我觉得值得记下来。",
        "",
        f"分类：{label}",
        f"内容：{candidate.content}",
    ]
    if candidate.reason:
        lines.append(f"用途：{candidate.reason}")
    lines += ["", "要存吗？"]
    return "\n".join(lines)


async def run_memory_flow(
    *,
    bot: Bot,
    settings: Settings,
    llm: LLMRouter,
    telegram_user_id: int,
    user_text: str,
    source_message_id: str | None = None,
) -> None:
    """在回复发出之后异步执行，不阻塞用户看到回复。"""
    try:
        extractor = MemoryExtractor(llm)
        result = await extractor.extract(user_text)
        if not result.candidates:
            return

        async with get_session_factory()() as session:
            user = await user_service.get_by_telegram_id(session, telegram_user_id)
            if user is None:
                return
            row = await user_service.get_settings_row(session, user)
            if not row.memory_enabled:
                return
            auto_enabled = bool(settings.memory_auto_save and row.auto_save_enabled)

            for candidate in result.candidates:
                verdict = review_candidate(candidate, auto_save_enabled=auto_enabled)

                if verdict.decision == Decision.DROP:
                    logger.info("候选被规则拒绝：%s", verdict.reason)
                    continue

                if verdict.decision == Decision.AUTO_SAVE:
                    memory, created = await manager.apply_auto_save(
                        session, user, candidate, verdict, source_message_id
                    )
                    if created and candidate.category != MemoryCategory.CONTEXT:
                        await bot.send_message(
                            telegram_user_id,
                            f"记下了：{memory.content}\n（不想让我记就说「忘掉」）",
                        )
                    continue

                saved = await manager.create_candidate(
                    session, user, candidate, verdict, source_message_id
                )
                await bot.send_message(
                    telegram_user_id,
                    _confirm_text(settings, candidate),
                    reply_markup=memory_candidate(saved.id),
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("记忆流水线出错：%s", exc)
