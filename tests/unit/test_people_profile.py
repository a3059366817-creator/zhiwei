"""P6 测试：个人画像 + 人物档案与关系。"""

from __future__ import annotations

import pytest

from app.agent.prompts import build_system_prompt
from app.database.connection import dispose_db, get_session_factory, init_db
from app.memory import manager
from app.memory.rules import review
from app.memory.schemas import ExtractedCandidate, MemoryCategory
from app.people import service as people
from app.profile.service import build_profile, render_profile_text
from app.services import user_service


@pytest.fixture
async def db():
    await init_db()
    yield
    await dispose_db()


async def _user(session, tid: int):
    return await user_service.get_or_create(session, telegram_id=tid)


# ---------------- 人物档案 ----------------
async def test_upsert_person_dedupes_by_name(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3001)
        a = await people.upsert_person(session, user, "妈妈")
        b = await people.upsert_person(session, user, " 妈妈 ")
        assert a.id == b.id
        rows = await people.list_people(session, user.id)
        assert len(rows) == 1


async def test_add_relationship_dedupes_same_type(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3002)
        person = await people.upsert_person(session, user, "小林")
        r1 = await people.add_relationship(session, user, person, "同事", "同一个组")
        r2 = await people.add_relationship(session, user, person, "同事", "同一个组，后端")
        assert r1.id == r2.id
        assert r2.description == "同一个组，后端"


async def test_delete_person_removes_relationships(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3003)
        person = await people.upsert_person(session, user, "老张")
        await people.add_relationship(session, user, person, "老板")

        assert await people.delete_person(session, user.id, person.id) is True
        assert await people.list_people(session, user.id) == []
        assert await people.get_person(session, user.id, person.id) is None


async def test_people_context_only_for_mentioned_names(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3004)
        mom = await people.upsert_person(session, user, "妈妈", "住在老家")
        await people.add_relationship(session, user, mom, "母亲")
        friend = await people.upsert_person(session, user, "小林")
        await people.add_relationship(session, user, friend, "同事")

        hits = await people.people_context(session, user.id, "我妈最近身体怎么样")
        assert len(hits) == 1
        assert "妈妈" in hits[0]
        assert "小林" not in "".join(hits)

        assert await people.people_context(session, user.id, "今天天气不错") == []


# ---------------- 画像 ----------------
async def test_profile_groups_and_renders(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3005)
        await manager.save_memory(session, user, category="profile", content="他在学人工智能")
        await manager.save_memory(session, user, category="preference", content="他喜欢喝冰美式")
        await manager.save_memory(
            session, user, category="experience", content="他在写一个 AI 助手"
        )

        grouped = await build_profile(session, user)
        assert "他在学人工智能" in grouped["profile"]
        assert "他喜欢喝冰美式" in grouped["preference"]

        text = render_profile_text("木川", grouped)
        assert "身份与技能" in text
        assert "偏好" in text
        assert "经历与项目" in text


async def test_empty_profile_message(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3006)
        grouped = await build_profile(session, user)
        assert render_profile_text("木川", grouped).startswith("我还什么都没记住")


# ---------------- 关系候选 -> 归档 ----------------
async def test_approve_relationship_candidate_creates_person(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3007)
        cand = ExtractedCandidate(
            category=MemoryCategory.RELATIONSHIP,
            content="他妈妈下个月生日",
            reason="家人日程",
            person_name="妈妈",
            relation_type="母亲",
        )
        row = await manager.create_candidate(session, user, cand, review(cand))
        assert row.person_name == "妈妈"

        memory = await manager.approve_candidate(session, row)
        assert memory.content == "他妈妈下个月生日"

        rows = await people.list_people(session, user.id)
        assert len(rows) == 1
        person, rels = rows[0]
        assert person.name == "妈妈"
        assert [r.relation_type for r in rels] == ["母亲"]


async def test_rejected_relationship_creates_no_person(db):
    async with get_session_factory()() as session:
        user = await _user(session, 3008)
        cand = ExtractedCandidate(
            category=MemoryCategory.RELATIONSHIP,
            content="他朋友叫小王",
            person_name="小王",
            relation_type="朋友",
        )
        row = await manager.create_candidate(session, user, cand, review(cand))
        await manager.reject_candidate(session, row)

        assert await people.list_people(session, user.id) == []


# ---------------- 提示词注入 ----------------
def test_prompt_includes_people_section():
    prompt = build_system_prompt(
        ai_name="知微",
        user_name="木川",
        memories=["他喜欢喝冰美式"],
        people=["妈妈（母亲）：下个月生日"],
    )
    assert "人物档案" in prompt
    assert "妈妈（母亲）" in prompt


def test_prompt_without_people_warns_not_to_guess():
    prompt = build_system_prompt(ai_name="知微", user_name="木川", people=[])
    assert "不要主动打探" in prompt
