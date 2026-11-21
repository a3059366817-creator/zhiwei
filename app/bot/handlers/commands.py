"""命令处理器：/start /help /new /model /history /id /chat。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    main_menu,
    memory_candidate,
    memory_list,
    people_list,
    reminder_list,
)
from app.bot.utils import answer_long
from app.conversation import service as conv_service
from app.core.config import Settings
from app.llm.router import LLMRouter
from app.memory import manager
from app.people.service import list_people
from app.profile.service import build_profile, render_profile_text
from app.reminders import service as reminders
from app.services import user_service

logger = logging.getLogger(__name__)
router = Router(name="commands")


@router.message(CommandStart())
async def on_start(message: Message, session: AsyncSession, settings: Settings) -> None:
    assert message.from_user is not None
    await user_service.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await message.answer(
        f"我是{settings.ai_name}。\n\n"
        f"以后想说什么直接说就行——今天干了什么、在想什么、遇到什么麻烦。"
        f"你说过的事我会记下来，慢慢地我会越来越了解你。\n\n"
        f"想换个话题就 /new。",
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def on_help(message: Message, settings: Settings) -> None:
    text = (
        f"我是{settings.ai_name}，直接跟我说话就好。\n\n"
        "命令（不常用）\n"
        "/new —— 开一段新对话\n"
        "/history —— 看最近聊了什么\n"
        "/model —— 看当前用的模型\n"
        "/memory —— 看我的记忆（P5 开放）\n"
        "/id —— 看你的 Telegram ID\n"
        "/help —— 这份说明"
    )
    await answer_long(message, text)


@router.message(Command("new", "chat"))
async def on_new(message: Message, session: AsyncSession, settings: Settings) -> None:
    assert message.from_user is not None
    user = await user_service.get_or_create(session, message.from_user.id)
    await conv_service.start_new_conversation(session, user)
    await message.answer("好，翻篇了。想聊点新的？")


@router.message(Command("todo", "todos", "remind"))
async def on_todo(message: Message, session: AsyncSession, settings: Settings) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer(
            "我们还没聊过。想让我提醒你什么，直接说就行，比如「明早七点半叫我起床」。"
        )
        return

    rows = await reminders.list_pending(session, user.id)
    if not rows:
        await message.answer("现在没有待办。直接跟我说「明天九点提醒我交周报」就行。")
        return

    lines = [f"你有 {len(rows)} 条待办："]
    for i, r in enumerate(rows, 1):
        when = reminders.fmt_local(r.due_at, settings.timezone)
        mark = " ⚠️已过期" if r.due_at and r.due_at < datetime.now(UTC) else ""
        lines.append(f"{i}. {r.title} · {when}{mark}")
    lines.append("")
    lines.append("点按钮完成，或发 /done 标题关键词")
    await answer_long(message, "\n".join(lines))
    await message.answer(
        "要划掉哪条？",
        reply_markup=reminder_list([(r.id, r.title) for r in rows[:6]]),
    )


@router.message(Command("done"))
async def on_done(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        return
    arg = (message.text or "").split(maxsplit=1)
    if len(arg) < 2:
        await message.answer("用法：/done 标题关键词")
        return

    kw = arg[1].strip()
    target = await reminders.find_by_keyword(session, user.id, kw)
    if target is None:
        await message.answer(f"没找到包含「{kw}」的待办。")
        return
    await reminders.complete(session, user.id, target.id)
    await message.answer(f"✅ 划掉了：{target.title}")


@router.message(Command("delay", "snooze"))
async def on_delay(message: Message, session: AsyncSession, settings: Settings) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("用法：/delay 标题关键词 20（推迟 20 分钟）")
        return
    kw, minutes = parts[1], parts[2]
    try:
        mins = int(minutes)
    except ValueError:
        await message.answer("分钟数要写数字，比如 20。")
        return

    target = await reminders.find_by_keyword(session, user.id, kw)
    if target is None:
        await message.answer(f"没找到包含「{kw}」的待办。")
        return
    row = await reminders.snooze(session, user.id, target.id, mins)
    when = reminders.fmt_local(row.due_at, settings.timezone) if row else ""
    await message.answer(f"⏰ 「{target.title}」改到 {when}")


@router.message(Command("cancel"))
async def on_cancel(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("用法：/cancel 标题关键词")
        return
    target = await reminders.find_by_keyword(session, user.id, parts[1].strip())
    if target is None:
        await message.answer("没找到这条待办。")
        return
    await reminders.cancel(session, user.id, target.id)
    await message.answer(f"🗑 删掉了：{target.title}")


@router.message(Command("model"))
async def on_model(message: Message, settings: Settings, llm: LLMRouter) -> None:
    names = llm.provider_names or ["（无）"]
    await message.answer(
        f"当前模型：{' → '.join(names)}\n"
        f"主：{settings.llm_provider}"
        + (f"\n备：{settings.llm_fallback_provider}" if settings.llm_fallback_provider else "")
    )


@router.message(Command("history"))
async def on_history(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer("你还没跟我聊过。")
        return
    conv = await conv_service.get_active_conversation(session, user)
    msgs = await conv_service.recent_messages(session, conv.id, limit=10)
    if not msgs:
        await message.answer("这一段对话还是空的。")
        return
    lines = []
    for m in msgs:
        who = "你" if m["role"] == "user" else "我"
        body = m["content"].replace("\n", " ")
        if len(body) > 60:
            body = body[:60] + "…"
        lines.append(f"{who}：{body}")
    await answer_long(message, "\n".join(lines))


@router.message(Command("id"))
async def on_id(message: Message) -> None:
    assert message.from_user is not None
    await message.answer(f"你的 Telegram ID：`{message.from_user.id}`")


CATEGORY_LABEL = {
    "profile": "身份",
    "preference": "偏好",
    "experience": "经历",
    "relationship": "关系",
    "context": "状态",
}


@router.message(Command("memory"))
async def on_memory(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer("我们还没聊过，暂时没有记忆。")
        return

    arg = ""
    if message.text:
        parts = message.text.split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

    # 暂停 / 恢复自动记忆
    if arg in ("off", "on"):
        await user_service.update_settings(session, user, auto_save_enabled=(arg == "on"))
        state = "开启" if arg == "on" else "暂停"
        await message.answer(f"好，自动记忆已{state}。重要信息仍然会问你。")
        return

    # 只看待确认
    if arg in ("pending", "待确认"):
        cands = await manager.pending_candidates(session, user.id, limit=10)
        if not cands:
            await message.answer("没有待确认的候选。")
            return
        for c in cands[:5]:
            label = CATEGORY_LABEL.get(c.category, c.category)
            await message.answer(
                f"这条要存吗？\n\n分类：{label}\n内容：{c.content}",
                reply_markup=memory_candidate(c.id),
            )
        return

    category = arg if arg in CATEGORY_LABEL else None
    if arg and category is None:
        await message.answer(
            "用法：\n"
            "/memory —— 看全部\n"
            "/memory preference —— 只看某一类\n"
            "  可选：profile / preference / experience / relationship / context\n"
            "/memory pending —— 只看待确认\n"
            "/memory off —— 暂停自动记忆\n"
            "/memory on —— 恢复自动记忆"
        )
        return

    rows = await manager.list_memories(session, user.id, category=category, limit=20)
    cands = await manager.pending_candidates(session, user.id, limit=10)

    if not rows and not cands:
        await message.answer("我还什么都没记住。多跟我说说你自己。")
        return

    if rows:
        title = f"我记得你 {len(rows)} 件事" + (
            f"（{CATEGORY_LABEL[category]}）" if category else ""
        )
        lines = [f"{title}："]
        for m in rows:
            lines.append(f"· [{CATEGORY_LABEL.get(m.category, m.category)}] {m.content}")
        await answer_long(message, "\n".join(lines))
        await message.answer(
            "点 ✏️ 改内容，点 🗑 删除。",
            reply_markup=memory_list([(m.id, m.content) for m in rows[:6]]),
        )

    if cands and not category:
        await message.answer(f"还有 {len(cands)} 条在等你确认，发 /memory pending 查看。")


@router.message(Command("profile"))
async def on_profile(message: Message, session: AsyncSession, settings: Settings) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer("我们还没聊过，我还不了解你。")
        return
    grouped = await build_profile(session, user)
    await answer_long(message, render_profile_text(settings.user_name, grouped))


@router.message(Command("people"))
async def on_people(message: Message, session: AsyncSession) -> None:
    assert message.from_user is not None
    user = await user_service.get_by_telegram_id(session, message.from_user.id)
    if user is None:
        await message.answer("我们还没聊过。")
        return

    rows = await list_people(session, user.id)
    if not rows:
        await message.answer(
            "你还没跟我介绍过身边的人。\n"
            "可以说「我妈下个月生日」这种，我确认之后会登记成人物档案。"
        )
        return

    lines = [f"我记着 {len(rows)} 个人："]
    for person, rels in rows:
        rel_text = "、".join(r.relation_type for r in rels) or "关系未明确"
        line = f"· {person.name}（{rel_text}）"
        if person.description:
            line += f"：{person.description}"
        lines.append(line)
    await answer_long(message, "\n".join(lines))
    await message.answer(
        "要删哪个人？点一下就把档案和关系一起删掉。",
        reply_markup=people_list([(p.id, p.name) for p, _ in rows[:6]]),
    )


@router.message(Command("settings"))
async def on_soon(message: Message) -> None:
    await message.answer("这个功能还没做（P8 之后）。")
