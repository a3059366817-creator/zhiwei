"""Assistant：把「人格 + 历史 + 记忆」拼成模型输入，并拿到回复。

这一层不认识 Telegram，也不认识数据库细节，方便以后接 Web 端。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import build_system_prompt
from app.conversation.service import recent_messages
from app.core.config import Settings
from app.database.models import Conversation, User
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class Assistant:
    def __init__(self, settings: Settings, router: LLMRouter) -> None:
        self.settings = settings
        self.router = router

    async def _memory_lines(self, session: AsyncSession, user: User, query: str) -> list[str]:
        """按当前消息检索相关的正式记忆（只注入必要的几条）。"""
        from app.memory.retriever import retrieve

        try:
            return await retrieve(session, user.id, query, limit=6)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆检索失败，按无记忆处理：%s", exc)
            return []

    async def reply(
        self, session: AsyncSession, user: User, conversation: Conversation
    ) -> tuple[str, str]:
        """返回 (回复文本, 模型名)。用户这条消息应当已经先落库。"""
        history = await recent_messages(session, conversation.id)
        if not history:
            raise ValueError("会话里没有消息，无法生成回复")

        last_user_text = next(
            (m["content"] for m in reversed(history) if m["role"] == "user"), ""
        )
        memories = await self._memory_lines(session, user, last_user_text)
        people = await self._people_lines(session, user, last_user_text)
        system_prompt = build_system_prompt(
            ai_name=self.settings.ai_name,
            user_name=self.settings.user_name,
            memories=memories,
            people=people,
            timezone=self.settings.timezone,
        )
        # 把当前时间贴到最后一条用户消息前面：历史里可能有旧时间，模型会抄，
        # 紧挨着问题的时间标记才能压过它。
        local_now = datetime.now(ZoneInfo(self.settings.timezone))
        stamp = local_now.strftime("%Y-%m-%d %H:%M %A")
        if history and history[-1]["role"] == "user":
            history = [
                *history[:-1],
                {
                    "role": "user",
                    "content": f"（当前时间 {stamp}）\n{history[-1]['content']}",
                },
            ]
        messages = [{"role": "system", "content": system_prompt}, *history]
        return await self.router.chat(messages)

    async def _people_lines(self, session: AsyncSession, user: User, query: str) -> list[str]:
        """只注入这句话里提到的人，避免无关隐私外泄。"""
        from app.people.service import people_context

        try:
            return await people_context(session, user.id, query, limit=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("人物档案检索失败：%s", exc)
            return []
