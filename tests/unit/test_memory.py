"""P5 记忆系统测试：规则、提取、确认、检索、隐私。"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.database.connection import dispose_db, get_session_factory, init_db
from app.memory import manager
from app.memory.extractor import MemoryExtractor, _extract_json_object
from app.memory.flow import run_memory_flow
from app.memory.retriever import retrieve
from app.memory.rules import review
from app.memory.schemas import Decision, ExtractedCandidate, MemoryCategory, Sensitivity
from app.services import user_service


@pytest.fixture
async def db():
    await init_db()
    yield
    await dispose_db()


def _cand(**kw) -> ExtractedCandidate:
    base = {
        "category": MemoryCategory.PREFERENCE,
        "content": "他喜欢用 Python 写东西",
        "reason": "技术偏好",
    }
    base.update(kw)
    return ExtractedCandidate(**base)


# ---------------- 规则 ----------------
def test_preference_auto_saves():
    r = review(_cand(), auto_save_enabled=True)
    assert r.decision == Decision.AUTO_SAVE


def test_auto_save_disabled_requires_confirm():
    r = review(_cand(), auto_save_enabled=False)
    assert r.decision == Decision.CONFIRM


def test_experience_needs_confirm():
    r = review(_cand(category=MemoryCategory.EXPERIENCE, content="他上周做完了一个项目"))
    assert r.decision == Decision.CONFIRM


def test_relationship_needs_confirm():
    r = review(
        _cand(category=MemoryCategory.RELATIONSHIP, content="他妹妹在读高中")
    )
    assert r.decision == Decision.CONFIRM


def test_sensitive_keywords_force_confirm_and_mark_sensitive():
    r = review(_cand(content="他工资大概一万五"))
    assert r.decision == Decision.CONFIRM
    assert r.sensitivity == Sensitivity.SENSITIVE


def test_credentials_are_dropped_entirely():
    r = review(_cand(content="他的银行卡号是 6222 1234"))
    assert r.decision == Decision.DROP
    r2 = review(_cand(content="服务器密码是 abc123"))
    assert r2.decision == Decision.DROP


# ---------------- 提取：JSON 容错 ----------------
def test_extract_json_plain():
    data = _extract_json_object('{"candidates":[]}')
    assert data == {"candidates": []}


def test_extract_json_fenced():
    raw = '```json\n{"candidates":[{"category":"preference"}]}\n```'
    data = _extract_json_object(raw)
    assert data is not None
    assert data["candidates"][0]["category"] == "preference"


def test_extract_json_garbage_returns_none():
    assert _extract_json_object("我不知道该说什么") is None
    assert _extract_json_object('{"candidates": [') is None


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def chat(self, messages, *, temperature=0.8, max_tokens=None):
        return self.payload, "fake"


async def test_extractor_parses_valid_json():
    llm = _FakeLLM(
        '{"candidates":[{"category":"preference","content":"他喜欢喝美式","reason":"饮食偏好"}]}'
    )
    result = await MemoryExtractor(llm).extract("我一般喝美式")
    assert len(result.candidates) == 1
    assert result.candidates[0].content == "他喜欢喝美式"


async def test_extractor_bad_json_yields_empty():
    result = await MemoryExtractor(_FakeLLM("抱歉，我不确定")).extract("随便说说")
    assert result.candidates == []


# ---------------- 入库与去重 ----------------
async def test_save_memory_dedupes_similar_content(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2001)
        m1, created1 = await manager.save_memory(
            session, user, category="preference", content="他喜欢喝美式咖啡"
        )
        m2, created2 = await manager.save_memory(
            session, user, category="preference", content="他喜欢喝美式咖啡。"
        )
        assert created1 is True
        assert created2 is False
        assert m1.id == m2.id
        rows = await manager.list_memories(session, user.id)
        assert len(rows) == 1


async def test_approve_candidate_creates_memory(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2002)
        cand = _cand(category=MemoryCategory.EXPERIENCE, content="他在开发一个 AI 助手")
        verdict = review(cand)
        row = await manager.create_candidate(session, user, cand, verdict, source_message_id=None)

        memory = await manager.approve_candidate(session, row)
        assert memory.content == cand.content
        assert row.status == "approved"
        assert len(await manager.list_memories(session, user.id)) == 1


async def test_reject_candidate_never_enters_memory(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2003)
        cand = _cand(category=MemoryCategory.EXPERIENCE, content="他去年去过日本")
        row = await manager.create_candidate(session, user, cand, review(cand))
        await manager.reject_candidate(session, row)

        assert await manager.list_memories(session, user.id) == []
        assert await manager.pending_candidates(session, user.id) == []


async def test_delete_memory_is_real_delete(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2004)
        memory, _ = await manager.save_memory(
            session, user, category="preference", content="他喜欢猫"
        )
        assert await manager.delete_memory(session, user.id, memory.id) is True
        assert await manager.get_memory(session, user.id, memory.id) is None
        assert await retrieve(session, user.id, "猫") == []


# ---------------- 检索 ----------------
async def test_retrieve_picks_relevant_memory(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2005)
        await manager.save_memory(
            session, user, category="preference", content="他喜欢用 Python 写爬虫"
        )
        await manager.save_memory(session, user, category="preference", content="他讨厌香菜")
        hits = await retrieve(session, user.id, "最近在用 python 做点东西")
        assert any("Python" in h for h in hits)
        assert all("香菜" not in h for h in hits)


async def test_retrieve_ignores_expired_context(db):
    from datetime import UTC, datetime, timedelta

    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=2006)
        await manager.save_memory(
            session,
            user,
            category="context",
            content="他这周在赶毕业设计",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        assert await retrieve(session, user.id, "毕业设计怎么样") == []


# ---------------- 端到端：流水线 ----------------
class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


def _settings(**kw) -> Settings:
    base = {"telegram_user_id": 2007, "llm_provider": "ollama", "memory_auto_save": True}
    base.update(kw)
    return Settings(**base)


async def test_flow_auto_saves_low_risk_and_notifies(db):
    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=2007)

    bot = _FakeBot()
    llm = _FakeLLM(
        '{"candidates":[{"category":"preference","content":"他喜欢喝冰美式","reason":"饮食偏好"}]}'
    )
    await run_memory_flow(
        bot=bot,
        settings=_settings(),
        llm=llm,
        telegram_user_id=2007,
        user_text="我每天都要喝冰美式",
    )
    assert len(bot.sent) == 1
    assert "记下了" in bot.sent[0]["text"]

    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 2007)
        rows = await manager.list_memories(session, user.id)
        assert any("冰美式" in r.content for r in rows)


async def test_flow_sensitive_never_auto_saves(db):
    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=2008)

    bot = _FakeBot()
    llm = _FakeLLM(
        '{"candidates":[{"category":"context","content":"他工资一万五","reason":"收入","sensitivity":"normal"}]}'
    )
    await run_memory_flow(
        bot=bot,
        settings=_settings(),
        llm=llm,
        telegram_user_id=2008,
        user_text="我工资一万五",
    )

    # 只能生成候选并询问，绝不能直接入库
    assert len(bot.sent) == 1
    assert "要存吗" in bot.sent[0]["text"]
    assert "reply_markup" in bot.sent[0]["kwargs"]

    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 2008)
        assert await manager.list_memories(session, user.id) == []
        assert len(await manager.pending_candidates(session, user.id)) == 1


async def test_flow_drops_credentials_without_asking(db):
    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=2009)

    bot = _FakeBot()
    llm = _FakeLLM(
        '{"candidates":[{"category":"profile","content":"他的银行卡号是 6222","reason":"财务"}]}'
    )
    await run_memory_flow(
        bot=bot,
        settings=_settings(),
        llm=llm,
        telegram_user_id=2009,
        user_text="我的银行卡号是6222",
    )
    assert bot.sent == []
    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 2009)
        assert await manager.list_memories(session, user.id) == []
        assert await manager.pending_candidates(session, user.id) == []
