"""会话与消息持久化测试。"""

import pytest

from app.conversation import service as conv
from app.database.connection import dispose_db, get_session_factory, init_db
from app.services import user_service


@pytest.fixture
async def db():
    await init_db()
    yield
    await dispose_db()


async def test_messages_persist_in_order(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=1001, display_name="测试")
        conv_obj = await conv.get_active_conversation(session, user)
        await conv.add_message(session, conv_obj, "user", "第一句")
        await conv.add_message(session, conv_obj, "assistant", "第一句的回复", model_name="fake")
        await conv.add_message(session, conv_obj, "user", "第二句")

        history = await conv.recent_messages(session, conv_obj.id)
        assert [m["content"] for m in history] == ["第一句", "第一句的回复", "第二句"]
        assert [m["role"] for m in history] == ["user", "assistant", "user"]


async def test_new_conversation_archives_old(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=1002)
        first = await conv.get_active_conversation(session, user)
        await conv.add_message(session, first, "user", "旧对话")

        second = await conv.start_new_conversation(session, user)
        assert second.id != first.id

        history = await conv.recent_messages(session, second.id)
        assert history == []

        again = await conv.get_active_conversation(session, user)
        assert again.id == second.id


async def test_history_limit(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=1003)
        c = await conv.get_active_conversation(session, user)
        for i in range(30):
            await conv.add_message(session, c, "user", f"msg-{i}")

        history = await conv.recent_messages(session, c.id, limit=5)
        assert len(history) == 5
        assert history[-1]["content"] == "msg-29"


async def test_get_or_create_is_idempotent(db):
    async with get_session_factory()() as session:
        a = await user_service.get_or_create(session, telegram_id=1004, username="muchuan")
        b = await user_service.get_or_create(session, telegram_id=1004, username="muchuan2")
        assert a.id == b.id
        assert b.username == "muchuan2"
