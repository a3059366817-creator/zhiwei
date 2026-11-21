"""Inline 按钮回调：菜单 + 记忆候选确认 + 记忆/人物编辑删除。"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu
from app.conversation import service as conv_service
from app.memory import manager, pending
from app.people import service as people_service
from app.services import user_service

logger = logging.getLogger(__name__)
router = Router(name="callbacks")


@router.callback_query(F.data.startswith("cmd:"))
async def on_menu(call: CallbackQuery, session: AsyncSession) -> None:
    action = (call.data or "").split(":", 1)[-1]
    assert call.from_user is not None

    if action == "new":
        user = await user_service.get_or_create(session, call.from_user.id)
        await conv_service.start_new_conversation(session, user)
        await call.message.answer("好，翻篇了。想聊点新的？")  # type: ignore[union-attr]
    elif action == "memory":
        await call.message.answer("用 /memory 看全部记忆和待确认的候选。")  # type: ignore[union-attr]
    elif action == "history":
        user = await user_service.get_by_telegram_id(session, call.from_user.id)
        if user:
            conv = await conv_service.get_active_conversation(session, user)
            msgs = await conv_service.recent_messages(session, conv.id, limit=6)
            body = "\n".join(
                f"{'你' if m['role'] == 'user' else '我'}：{m['content'][:40]}" for m in msgs
            )
            await call.message.answer(body or "这一段还是空的。")  # type: ignore[union-attr]
    elif action == "model":
        await call.message.answer("用 /model 查看。")  # type: ignore[union-attr]

    await call.answer()
    try:
        await call.message.edit_reply_markup(reply_markup=main_menu())  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


@router.callback_query(F.data.startswith("mem:"))
async def on_memory_action(call: CallbackQuery, session: AsyncSession) -> None:
    """mem:<action>:<id>，id 可能是候选，也可能是已入库记忆。"""
    assert call.from_user is not None
    user = await user_service.get_by_telegram_id(session, call.from_user.id)
    if user is None:
        await call.answer("没找到你的记录")
        return

    parts = (call.data or "").split(":")
    if len(parts) < 3:
        await call.answer("参数不对")
        return
    action, target_id = parts[1], parts[2]
    message = call.message

    # --- 候选：保存 / 暂不 / 以后别问 / 修改 ---
    candidate = await manager.get_candidate(session, target_id)
    if candidate is not None and candidate.status == "pending":
        if action == "save":
            memory = await manager.approve_candidate(session, candidate)
            await call.answer("记住了")
            if message is not None:
                await message.edit_text(f"已记住：{memory.content}")
            return
        if action == "skip":
            await manager.reject_candidate(session, candidate)
            await call.answer("好，这条不记了")
            if message is not None:
                await message.edit_text(f"好，这条不记了：{candidate.content}")
            return
        if action == "never":
            await manager.never_ask_candidate(session, candidate)
            await call.answer("行，这条以后不问了")
            if message is not None:
                await message.edit_text(f"行，这条以后不问了：{candidate.content}")
            return
        if action == "edit":
            pending.set_edit(call.from_user.id, "candidate", target_id)
            await call.answer("把修改后的内容发给我")
            if message is not None:
                await message.edit_text(
                    f"当前内容：{candidate.content}\n\n把修改后的内容发给我，我按新内容问你。"
                )
            return

    # --- 已入库记忆：修改 / 删除 ---
    if action == "edit":
        memory = await manager.get_memory(session, user.id, target_id)
        if memory is None:
            await call.answer("这条记忆已经不在清单里了")
            return
        pending.set_edit(call.from_user.id, "memory", target_id)
        await call.answer("把新的写法发给我")
        if message is not None:
            await message.edit_text(
                f"现在记的是：{memory.content}\n\n把想替换成的写法发给我，我直接改掉。"
            )
        return

    if action == "del":
        ok = await manager.delete_memory(session, user.id, target_id)
        await call.answer("已删除" if ok else "这条已经不在了")
        if ok and message is not None:
            await message.edit_text("已删除。这条以后不会再被检索到。")
        return

    await call.answer()


@router.callback_query(F.data.startswith("rem:"))
async def on_reminder_action(call: CallbackQuery, session: AsyncSession, settings) -> None:
    """rem:<done|snooze>:<id> —— 提醒卡片上的按钮。"""
    from app.reminders import service as reminders

    assert call.from_user is not None
    parts = (call.data or "").split(":")
    if len(parts) < 3:
        await call.answer()
        return
    action, rid = parts[1], parts[2]

    user = await user_service.get_by_telegram_id(session, call.from_user.id)
    if user is None:
        await call.answer("没找到你的记录")
        return

    if action == "done":
        row = await reminders.complete(session, user.id, rid)
        if row is None:
            await call.answer("这条已经不在了")
            return
        await call.answer("干得好")
        if call.message is not None:
            await call.message.edit_text(f"✅ {row.title} —— 完成了")
        return

    if action == "snooze":
        row = await reminders.snooze(session, user.id, rid, 20)
        if row is None:
            await call.answer("这条已经不在了")
            return
        when = reminders.fmt_local(row.due_at, settings.timezone)
        await call.answer(f"改到 {when}")
        if call.message is not None:
            await call.message.edit_text(f"⏰ {row.title} —— 推迟到 {when}")
        return

    await call.answer()


@router.callback_query(F.data.startswith("ppl:"))
async def on_people_action(call: CallbackQuery, session: AsyncSession) -> None:
    """ppl:<name|desc|rel|del>:<person_id>"""
    assert call.from_user is not None
    user = await user_service.get_by_telegram_id(session, call.from_user.id)
    if user is None:
        await call.answer("没找到你的记录")
        return

    parts = (call.data or "").split(":")
    if len(parts) < 3:
        await call.answer()
        return
    action, person_id = parts[1], parts[2]
    person = await people_service.get_person(session, user.id, person_id)
    if person is None:
        await call.answer("这个人已经不在了")
        return

    rels = await people_service.relations_of(session, person.id)
    rel_text = "、".join(r.relation_type for r in rels) or "未明确"
    message = call.message

    if action == "del":
        ok = await people_service.delete_person(session, user.id, person_id)
        await call.answer("已删除" if ok else "这个人已经不在了")
        if ok and message is not None:
            await message.edit_text(f"已删除 {person.name} 的档案和关系。")
        return

    prompt = {
        "name": f"现在叫他「{person.name}」。发一个新的称呼给我。",
        "desc": f"{person.name} 现在的备注是：{person.description or '（空）'}\n发新的备注给我。",
        "rel": (
            f"{person.name} 现在的关系是「{rel_text}」。\n"
            "发新的关系给我，比如：同事 / 大学室友 / 表哥。"
        ),
    }.get(action)
    kind = {"name": "person_name", "desc": "person_desc", "rel": "relation"}.get(action)
    if prompt is None or kind is None:
        await call.answer()
        return

    pending.set_edit(call.from_user.id, kind, person_id)
    await call.answer("发新内容给我")
    if message is not None:
        await message.edit_text(prompt)
