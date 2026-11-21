"""Telegram Webhook 入口（Render 部署时使用）。

安全规则（规格 8.1）：
1. 只有 BOT_MODE=webhook 时才接受请求，轮询模式下直接拒绝，避免重复处理；
2. 必须配置 TELEGRAM_WEBHOOK_SECRET，否则拒绝（防止伪造更新）；
3. Secret 不匹配 → 403，且不进入任何消息处理流程。
"""

from __future__ import annotations

import logging

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    settings = get_settings()

    if settings.bot_mode != "webhook":
        raise HTTPException(status_code=404, detail="webhook disabled")

    secret = settings.telegram_webhook_secret
    if not secret:
        logger.error("处于 webhook 模式但没有配置 TELEGRAM_WEBHOOK_SECRET，拒绝所有请求")
        raise HTTPException(status_code=503, detail="webhook secret not configured")

    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if token != secret:
        logger.warning("Webhook 密钥不匹配，已拒绝")
        raise HTTPException(status_code=403, detail="forbidden")

    bot = getattr(request.app.state, "bot", None)
    dp = getattr(request.app.state, "dp", None)
    if bot is None or dp is None:
        raise HTTPException(status_code=503, detail="bot not running")

    try:
        payload = await request.json()
        update = Update.model_validate(payload, context={"bot": bot})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid update") from exc

    await dp.feed_update(bot, update)
    return {"ok": True}
