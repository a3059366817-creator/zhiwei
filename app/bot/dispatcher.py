"""Bot 与 Dispatcher 的组装。"""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from app.agent.assistant import Assistant
from app.bot.handlers import callbacks, chat, commands
from app.bot.middlewares import AccessMiddleware, DbSessionMiddleware
from app.core.config import Settings
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    # 不设置 parse_mode：纯文本最安全，避免用户输入里的符号被当成 HTML
    session = None
    if settings.telegram_proxy:
        session = AiohttpSession(proxy=settings.telegram_proxy)
        logger.info("Telegram 走代理：%s", settings.telegram_proxy)
    return Bot(token=settings.telegram_bot_token, session=session)


def create_dispatcher(
    settings: Settings, assistant: Assistant, llm: LLMRouter
) -> Dispatcher:
    dp = Dispatcher()

    access = AccessMiddleware(settings)
    db = DbSessionMiddleware()
    for observer in (dp.message, dp.callback_query):
        observer.middleware(access)
        observer.middleware(db)

    dp.include_router(commands.router)
    dp.include_router(callbacks.router)
    dp.include_router(chat.router)

    # 处理器通过参数名拿到这些依赖
    dp["settings"] = settings
    dp["assistant"] = assistant
    dp["llm"] = llm
    return dp
