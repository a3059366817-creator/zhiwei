"""提醒系统测试：标签解析、到期判定、完成/推迟、时区换算。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.database.connection import dispose_db, get_session_factory, init_db
from app.reminders import service as reminders
from app.reminders.tags import parse_actions, parse_local_datetime
from app.services import user_service

TZ = "Asia/Shanghai"


@pytest.fixture
async def db():
    await init_db()
    # 每个用例从干净的提醒表开始：due_for_nudge 是全局查询（调度器要处理所有用户）
    from sqlalchemy import delete

    from app.database.models import Reminder

    async with get_session_factory()() as session:
        await session.execute(delete(Reminder))
        await session.commit()
    yield
    await dispose_db()


# ---------------- 标签解析 ----------------
def test_parse_todo_with_time():
    r = parse_actions("行，明早七点半喊你。\n[[TODO:叫我起床|2026-11-22T07:30]]")
    assert r.text == "行，明早七点半喊你。"
    assert len(r.todos) == 1
    assert r.todos[0][0] == "叫我起床"
    assert r.todos[0][1] == datetime(2026, 11, 22, 7, 30)


def test_parse_todo_without_time():
    r = parse_actions("记下了。[[TODO:买牛奶]]")
    assert r.todos[0] == ("买牛奶", None)
    assert "[[" not in r.text


def test_parse_done():
    r = parse_actions("好，划掉了。[[DONE:交周报]]")
    assert r.done == ["交周报"]
    assert "DONE" not in r.text


def test_parse_multiple_and_stray_lines():
    raw = "嗯。\n[[TODO:A|2026-11-22T09:00]]\n[[TODO:B]]\nTODO: 这行是模型跑偏\n[[DONE:A]]"
    r = parse_actions(raw)
    assert [t[0] for t in r.todos] == ["A", "B"]
    assert r.done == ["A"]
    assert "TODO" not in r.text


def test_parse_actions_plain_text_untouched():
    r = parse_actions("今天天气不错，出去走走？")
    assert r.text == "今天天气不错，出去走走？"
    assert r.todos == [] and r.done == []


def test_parse_local_datetime_formats():
    assert parse_local_datetime("2026-11-22T07:30") == datetime(2026, 11, 22, 7, 30)
    assert parse_local_datetime("2026-11-22 07:30") == datetime(2026, 11, 22, 7, 30)
    assert parse_local_datetime("坏掉的字符串") is None


def test_timezone_conversion_roundtrip():
    naive = datetime(2026, 11, 22, 7, 30)
    utc = reminders.to_utc(naive, TZ)
    assert utc.tzinfo is not None
    assert utc.hour == 23 and utc.day == 21  # 上海 07:30 = 前一日 23:30 UTC
    back = reminders.to_local(utc, TZ)
    assert (back.hour, back.minute) == (7, 30)


# ---------------- 数据操作 ----------------
async def test_create_and_list_pending(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=6001)
        due = datetime.now(UTC) + timedelta(hours=2)
        await reminders.create_reminder(session, user, "交周报", due)
        await reminders.create_reminder(session, user, "买牛奶", None)

        rows = await reminders.list_pending(session, user.id)
        assert len(rows) == 2
        # 有时间的排前面
        assert rows[0].title == "交周报"


async def test_due_for_nudge_only_when_due(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=6002)
        now = datetime.now(UTC)
        await reminders.create_reminder(session, user, "未来的事", now + timedelta(hours=1))
        await reminders.create_reminder(session, user, "到点了", now - timedelta(seconds=5))

        due = await reminders.due_for_nudge(session, now)
        assert [r.title for r in due] == ["到点了"]


async def test_nudge_cap_and_gap(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=6003)
        now = datetime.now(UTC)
        row = await reminders.create_reminder(session, user, "一直拖", now - timedelta(minutes=1))

        # 第一次可以推
        assert len(await reminders.due_for_nudge(session, now)) == 1
        await reminders.mark_reminded(session, row)
        # 冷却期内不再推
        assert await reminders.due_for_nudge(session, now) == []
        # 冷却结束后可以推
        later = now + timedelta(minutes=25)
        assert len(await reminders.due_for_nudge(session, later)) == 1

        # 推满 3 次就不再推
        row.remind_count = 3
        row.last_remind_at = None
        await session.commit()
        assert await reminders.due_for_nudge(session, later) == []


async def test_complete_and_snooze(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=6004)
        now = datetime.now(UTC)
        row = await reminders.create_reminder(session, user, "写周报", now - timedelta(minutes=5))

        snoozed = await reminders.snooze(session, user.id, row.id, 20)
        assert snoozed is not None
        due = snoozed.due_at if snoozed.due_at.tzinfo else snoozed.due_at.replace(tzinfo=UTC)
        assert due > now
        assert snoozed.last_remind_at is None

        done = await reminders.complete(session, user.id, row.id)
        assert done is not None and done.status == "done"
        assert await reminders.list_pending(session, user.id) == []


async def test_keyword_lookup_and_cancel(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=6005)
        await reminders.create_reminder(session, user, "给妈妈买生日礼物", None)

        found = await reminders.find_by_keyword(session, user.id, "生日")
        assert found is not None
        assert await reminders.cancel(session, user.id, found.id) is not None
        assert await reminders.list_pending(session, user.id) == []


async def test_reminder_is_user_scoped(db):
    async with get_session_factory()() as session:
        a = await user_service.get_or_create(session, telegram_id=6006)
        b = await user_service.get_or_create(session, telegram_id=6007)
        row = await reminders.create_reminder(session, a, "只有A能看到", None)

        assert await reminders.get_reminder(session, b.id, row.id) is None
        assert await reminders.complete(session, b.id, row.id) is None
        assert await reminders.list_pending(session, b.id) == []
