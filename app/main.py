"""FastAPI 应用入口 + Telegram Bot 生命周期。

本地：BOT_MODE=polling，进程启动即开始收消息。
云端：BOT_MODE=webhook，由 POST /webhook/telegram 驱动。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.agent.assistant import Assistant
from app.api.routes import router as api_router
from app.api.v1 import router as v1_router
from app.api.webhook import router as webhook_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.database.connection import dispose_db
from app.llm.router import LLMRouter

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


def _upgrade_schema() -> None:
    """执行 alembic upgrade head。

    在独立线程里跑，因为 env.py 内部用 asyncio.run 建异步连接。
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


async def _self_ping_loop(settings) -> None:
    """每 N 分钟请求一次自己的 /health，避免免费实例休眠。"""
    import httpx

    url = f"{settings.public_base_url.rstrip('/')}/health"
    interval = max(1, settings.self_ping_minutes) * 60
    while True:
        await asyncio.sleep(interval)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url)
            logger.info("自保活 ping 成功：%s", r.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("自保活 ping 失败：%s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info(
        "知微启动：env=%s provider=%s mode=%s",
        settings.app_env,
        settings.llm_provider,
        settings.bot_mode,
    )
    # 表结构统一由 Alembic 管理，避免 create_all 与迁移脚本脱节
    await asyncio.to_thread(_upgrade_schema)
    logger.info("数据库已迁移到最新版本")

    llm = LLMRouter(settings)
    assistant = Assistant(settings, llm)
    app.state.llm = llm
    app.state.assistant = assistant
    app.state.bot = None
    app.state.dp = None
    app.state.scheduler = None

    poll_task: asyncio.Task | None = None
    self_ping_task: asyncio.Task | None = None
    scheduler = None
    bot = None
    if settings.telegram_bot_token:
        # 延迟导入：测试环境不需要 aiogram 的完整初始化开销
        from app.bot.dispatcher import create_bot, create_dispatcher

        bot = create_bot(settings)
        dp = create_dispatcher(settings, assistant, llm)
        app.state.bot = bot
        app.state.dp = dp
        if settings.bot_mode == "polling":
            poll_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

            def _report(t: asyncio.Task) -> None:
                if t.cancelled():
                    return
                exc = t.exception()
                if exc is not None:
                    logger.error("轮询任务异常退出：%r", exc)

            poll_task.add_done_callback(_report)
            logger.info("Bot 已启动（长轮询）")
        else:
            logger.info("Bot 处于 webhook 模式，等待 POST /webhook/telegram")

        # 自保活：Render 免费实例 15 分钟无入站请求会休眠。
        # 进程自己每 10 分钟请求一次公网地址，就算"有流量"，从而保持清醒。
        if settings.public_base_url and settings.self_ping_minutes > 0:
            self_ping_task = asyncio.create_task(_self_ping_loop(settings))
            logger.info(
                "自保活已启动：每 %s 分钟 ping %s/health",
                settings.self_ping_minutes,
                settings.public_base_url,
            )

        # 提醒调度器：进程醒着就每 30 秒检查一次；外部 cron 也可以打 /api/v1/internal/tick
        from app.reminders.scheduler import ReminderScheduler

        scheduler = ReminderScheduler(bot, settings, llm)
        app.state.scheduler = scheduler
        await scheduler.start()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN 未配置，Bot 不会启动")

    try:
        yield
    finally:
        if self_ping_task is not None:
            self_ping_task.cancel()
        if scheduler is not None:
            await scheduler.stop()
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if bot is not None:
            await bot.session.close()
        await dispose_db()
        logger.info("知微已停止")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.ai_name} ZhiWei",
        version="0.1.0",
        description="私人 Telegram AI 伙伴（V1.0）",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    app.include_router(v1_router)
    app.include_router(webhook_router)
    return app


app = create_app()
