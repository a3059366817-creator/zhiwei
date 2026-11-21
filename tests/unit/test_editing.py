"""P6+ 编辑/替换能力测试：记忆改内容、人物改称呼/备注/关系、待编辑状态。"""

from __future__ import annotations

import pytest

from app.database.connection import dispose_db, get_session_factory, init_db
from app.memory import manager, pending
from app.people import service as people
from app.services import user_service


@pytest.fixture
async def db():
    await init_db()
    yield
    await dispose_db()


async def test_update_memory_replaces_content(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4001)
        memory, _ = await manager.save_memory(
            session, user, category="preference", content="他喜欢喝美式"
        )
        updated = await manager.update_memory(
            session, user.id, memory.id, "他其实更喜欢拿铁，美式只是偶尔喝"
        )
        assert updated is not None
        assert "拿铁" in updated.content

        # 检索应命中新内容，旧说法不再单独存在
        from app.memory.retriever import retrieve

        hits = await retrieve(session, user.id, "今天想喝拿铁")
        assert any("拿铁" in h for h in hits)


async def test_update_memory_rejects_foreign_user(db):
    async with get_session_factory()() as session:
        owner = await user_service.get_or_create(session, telegram_id=4002)
        other = await user_service.get_or_create(session, telegram_id=4003)
        memory, _ = await manager.save_memory(
            session, owner, category="preference", content="他喜欢猫"
        )
        assert await manager.update_memory(session, other.id, memory.id, "篡改") is None


async def test_rename_person(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4004)
        person = await people.upsert_person(session, user, "小林")
        updated = await people.update_person(session, user.id, person.id, name="林工")
        assert updated is not None
        assert updated.name == "林工"


async def test_rename_into_existing_person_merges(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4005)
        a = await people.upsert_person(session, user, "小林")
        await people.add_relationship(session, user, a, "同事")
        b = await people.upsert_person(session, user, "林工")
        await people.add_relationship(session, user, b, "朋友")

        merged = await people.update_person(session, user.id, b.id, name="小林")
        assert merged is not None
        assert merged.id == a.id

        rows = await people.list_people(session, user.id)
        assert len(rows) == 1
        person, rels = rows[0]
        assert person.name == "小林"
        assert {r.relation_type for r in rels} == {"同事", "朋友"}


async def test_update_person_description(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4006)
        person = await people.upsert_person(session, user, "妈妈")
        updated = await people.update_person(
            session, user.id, person.id, description="住在老家，下个月生日"
        )
        assert updated is not None
        assert "下个月生日" in (updated.description or "")


async def test_set_relation_replaces(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4007)
        person = await people.upsert_person(session, user, "小林")
        await people.add_relationship(session, user, person, "朋友")
        rel = await people.set_relation(session, user, person, "大学室友")

        rels = await people.relations_of(session, person.id)
        assert len(rels) == 1
        assert rels[0].relation_type == "大学室友"
        assert rel.id == rels[0].id


def test_pending_edit_state_machine():
    pending.set_edit(1, "memory", "m-1")
    assert pending.peek_edit(1).kind == "memory"

    pending.set_edit(1, "relation", "p-1", extra="x")
    assert pending.peek_edit(1).kind == "relation"

    got = pending.pop_edit(1)
    assert got is not None and got.target_id == "p-1"
    assert pending.peek_edit(1) is None
    assert pending.pop_edit(1) is None


async def test_deleted_memory_cannot_be_edited(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=4008)
        memory, _ = await manager.save_memory(
            session, user, category="profile", content="他在读研"
        )
        await manager.delete_memory(session, user.id, memory.id)
        assert await manager.update_memory(session, user.id, memory.id, "他在工作") is None
