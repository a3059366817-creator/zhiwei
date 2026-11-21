"""提醒调度器。

两个驱动方式，互为补充：
1. 进程内 asyncio 循环（每 30 秒）——服务醒着时按时推送；
2. POST /internal/tick ——给外部 cron 用，能把 Render 从休眠中唤醒并立刻检查。

云端免费实例 15 分钟无请求会休眠，所以两者缺一不可。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from aiogram import Bot

from app.bot.keyboards import reminder_actions
from app.core.config import Settings
from app.database.connection import get_session_factory
from app.llm.base import LLMError
from app.llm.router import LLMRouter
from app.reminders import service as reminders
from app.services import user_service

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bot: Bot | None, settings: Settings, llm: LLMRouter) -> None:
        self.bot = bot
        self.settings = settings
        self.llm = llm
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.bot is None or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="reminder-loop")
        logger.info("提醒调度器已启动（每 30 秒）")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.exception("提醒循环出错：%s", exc)
            await asyncio.sleep(30)

    async def tick(self) -> int:
        """检查一次到期提醒，返回推送条数。可被外部 HTTP 触发。"""
        if self.bot is None:
            return 0
        if self._lock.locked():
            return 0
        async with self._lock:
            sent = 0
            now = datetime.now(UTC)
            async with get_session_factory()() as session:
                due = await reminders.due_for_nudge(
                    session, now, max_nudges=3, gap_minutes=20
                )
                for row in due:
                    user = await user_service.get_or_create(
                        session, self.settings.telegram_user_id
                    )
                    if row.user_id != user.id:
                        continue
                    text = await self._nudge_text(row)
                    when = reminders.fmt_local(row.due_at, self.settings.timezone)
                    body = f"{text}\n\n（#{self._short(row.id)} {row.title} · {when}）"
                    try:
                        await self.bot.send_message(
                            chat_id=self.settings.telegram_user_id,
                            text=body,
                            reply_markup=reminder_actions(row.id),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("提醒发送失败：%s", exc)
                        continue
                    await reminders.mark_reminded(session, row)
                    sent += 1
                    logger.info("已推送提醒：%s", row.title)
            return sent

    async def _nudge_text(self, row) -> str:
        when = reminders.fmt_local(row.due_at, self.settings.timezone)
        retry = "（你已经提醒过一次了，还没做）" if row.remind_count else ""
        prompt = (
            f"（系统指令，用户看不到这句）现在是 "
            f"{datetime.now(UTC).astimezone().strftime('%H:%M')}，"
            f"待办「{row.title}」原定 {when} 到点了{retry}。"
            "用一到两句像朋友那样提醒他：具体、口语，不要「温馨提示」「别忘了哦」这种套话，"
            "不要说教，不要列清单。只输出提醒文案本身。"
        )
        try:
            text, _model = await self.llm.chat(
                [
                    {"role": "system", "content": "你是一个朋友，说话简短自然。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=120,
            )
            return text.strip() or f"到点了：{row.title}"
        except LLMError as exc:
            logger.warning("提醒文案生成失败，用模板：%s", exc)
            return f"到点了：{row.title}"

    @staticmethod
    def _short(rid: str) -> str:
        return rid[:4]
