"""普通文本消息：存库 → 生成回复 → 解析提醒标签 → 存库 → 发出 → 异步记忆流水线。"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.assistant import Assistant
from app.bot.keyboards import memory_candidate
from app.bot.utils import answer_long
from app.conversation import service as conv_service
from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.router import LLMRouter
from app.memory import manager, pending
from app.memory.flow import run_memory_flow
from app.people import service as people_service
from app.reminders import service as reminders
from app.reminders.tags import parse_actions
from app.services import user_service

logger = logging.getLogger(__name__)
router = Router(name="chat")


async def _handle_pending_edit(
    message: Message, session: AsyncSession, text: str, user_id: int, settings: Settings
) -> bool:
    """用户正在修改候选 / 记忆 / 人物信息。"""
    edit = pending.peek_edit(user_id)
    if edit is None:
        return False
    pending.clear(user_id)

    if edit.kind == "candidate":
        row = await manager.get_candidate(session, edit.target_id)
        if row is None or row.status != "pending":
            await message.answer("那条候选已经处理过了。")
            return True
        row.content = text.strip()
        await session.commit()
        await message.answer("改好了，这样存吗？", reply_markup=memory_candidate(row.id))
        return True

    if edit.kind == "memory":
        user = await user_service.get_by_telegram_id(session, user_id)
        if user is None:
            await message.answer("没找到你的记录。")
            return True
        updated = await manager.update_memory(session, user.id, edit.target_id, text)
        if updated is None:
            await message.answer("这条记忆已经不在了。")
            return True
        await message.answer(f"改好了，现在是：\n{updated.content}")
        return True

    if edit.kind in ("person_name", "person_desc", "relation"):
        user = await user_service.get_by_telegram_id(session, user_id)
        if user is None:
            await message.answer("没找到你的记录。")
            return True
        person = await people_service.get_person(session, user.id, edit.target_id)
        if person is None:
            await message.answer("这个人的档案已经不在了。")
            return True
        if edit.kind == "person_name":
            updated = await people_service.update_person(
                session, user.id, edit.target_id, name=text
            )
            name = updated.name if updated else person.name
            await message.answer(f"改好了，以后叫他「{name}」。")
        elif edit.kind == "person_desc":
            await people_service.update_person(session, user.id, edit.target_id, description=text)
            await message.answer(f"备注更新了：{text}")
        else:
            rel = await people_service.set_relation(session, user, person, text)
            await message.answer(f"好，{person.name} 的关系改成「{rel.relation_type}」。")
        return True

    return False


async def _apply_reminder_tags(
    session: AsyncSession, user, parsed, settings: Settings
) -> list[str]:
    """把模型回复里的 [[TODO]] / [[DONE]] 落到数据库，返回给用户看的确认行。"""
    notes: list[str] = []

    for title, due_naive in parsed.todos:
        due = reminders.to_utc(due_naive, settings.timezone) if due_naive else None
        row = await reminders.create_reminder(session, user, title, due, source="chat")
        when = reminders.fmt_local(row.due_at, settings.timezone)
        notes.append(f"📌 已记下：{row.title}" + (f"（{when}）" if row.due_at else "（没定时间）"))

    for ref in parsed.done:
        target = None
        if ref.isdigit():
            target = await reminders.get_reminder(session, user.id, ref)
        if target is None:
            target = await reminders.find_by_keyword(session, user.id, ref)
        if target is not None:
            await reminders.complete(session, user.id, target.id)
            notes.append(f"✅ 划掉了：{target.title}")

    return notes


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(
    message: Message,
    session: AsyncSession,
    assistant: Assistant,
    settings: Settings,
    llm: LLMRouter,
) -> None:
    assert message.from_user is not None
    user_id = message.from_user.id
    text = (message.text or "").strip()
    if not text:
        return

    if await _handle_pending_edit(message, session, text, user_id, settings):
        return

    user = await user_service.get_or_create(
        session,
        user_id,
        message.from_user.username,
        message.from_user.first_name,
    )
    conv = await conv_service.get_active_conversation(session, user)
    await conv_service.add_message(session, conv, "user", text)

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

    try:
        raw, model_name = await assistant.reply(session, user, conv)
    except LLMError as exc:
        logger.warning("模型调用失败：%s", exc)
        await message.answer(f"我这会儿脑子不太转（{type(exc).__name__}）。稍等再跟我说一次？")
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成回复时出现未预期错误")
        await message.answer("出了点小状况，你再试一次？")
        raise exc

    parsed = parse_actions(raw)
    notes = await _apply_reminder_tags(session, user, parsed, settings)
    body = "\n\n".join([parsed.text or "嗯。", *notes]) if notes else (parsed.text or "嗯。")

    await conv_service.add_message(
        session, conv, "assistant", parsed.text or "嗯。", model_name=model_name
    )
    await answer_long(message, body)

    # 记忆流水线放后台，不拖慢回复
    asyncio.create_task(
        run_memory_flow(
            bot=message.bot,  # type: ignore[arg-type]
            settings=settings,
            llm=llm,
            telegram_user_id=user_id,
            user_text=text,
            source_message_id=None,
        )
    )
