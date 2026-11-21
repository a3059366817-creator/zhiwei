"""Telegram Webhook 入口（Render 部署时使用）。

安全规则（规格 8.1）：
1. 只有 BOT_MODE=webhook 时才接受请求，轮询模式下直接拒绝；
2. 必须配置 TELEGRAM_WEBHOOK_SECRET，否则拒绝（防伪造）；
3. Secret 不匹配 → 403，不进入任何处理流程。

可靠性：
4. **立即回 200**，把处理放到后台任务——否则模型一次调用要 20~45 秒，
   Telegram 等不及会重投同一个 update，导致重复回复、重复建提醒；
5. 用 update_id 去重，一旦重投也不会重复处理。
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 最近处理过的 update_id（去重），上限防止内存膨胀
_SEEN: OrderedDict[int, None] = OrderedDict()
_SEEN_MAX = 500


def _seen_before(update_id: int) -> bool:
    if update_id in _SEEN:
        return True
    _SEEN[update_id] = None
    while len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    return False


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    settings = get_settings()

    if settings.bot_mode != "webhook":
        raise HTTPException(status_code=404, detail="webhook disabled")

    secret = settings.telegram_webhook_secret
    if not secret:
        logger.error("webhook 模式但没有配置 TELEGRAM_WEBHOOK_SECRET，拒绝所有请求")
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

    if _seen_before(update.update_id):
        logger.info("重复投递的 update %s，已跳过", update.update_id)
        return {"ok": True, "duplicate": True}

    async def _process() -> None:
        try:
            await dp.feed_update(bot, update)
        except Exception:  # noqa: BLE001
            logger.exception("处理 update %s 失败", update.update_id)

    asyncio.create_task(_process())
    return {"ok": True}
