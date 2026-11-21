"""P8 安全与验收测试。

对照规格 10.4 隐私测试逐条验证：
1. 用户拒绝保存后，候选不得进入正式记忆
2. 用户删除后，记忆不能再次被检索
3. 未授权用户无法访问数据
4. 敏感信息不会被自动写入长期记忆
5. 记忆候选不能绕过确认机制
6. Webhook 无效请求不能进入消息处理流程
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import get_settings
from app.database.connection import dispose_db, get_session_factory, init_db
from app.memory import manager
from app.memory.flow import run_memory_flow
from app.memory.retriever import retrieve
from app.memory.rules import review
from app.memory.schemas import ExtractedCandidate, MemoryCategory
from app.services import user_service


@pytest.fixture
async def db():
    await init_db()
    yield
    await dispose_db()


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


class FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def chat(self, messages, *, temperature=0.8, max_tokens=None):
        return self.payload, "fake"


# ---------- 1. 拒绝后不得入库 ----------
async def test_rejected_candidate_never_enters_memory(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=5001)
        cand = ExtractedCandidate(
            category=MemoryCategory.EXPERIENCE, content="他上周去了趟西藏"
        )
        row = await manager.create_candidate(session, user, cand, review(cand))
        await manager.reject_candidate(session, row)

        assert await manager.list_memories(session, user.id) == []
        assert await retrieve(session, user.id, "西藏") == []
        assert await manager.pending_candidates(session, user.id) == []


# ---------- 2. 删除后不可检索 ----------
async def test_deleted_memory_not_retrievable(db):
    async with get_session_factory()() as session:
        user = await user_service.get_or_create(session, telegram_id=5002)
        memory, _ = await manager.save_memory(
            session, user, category="preference", content="他非常讨厌开会"
        )
        assert any("开会" in h for h in await retrieve(session, user.id, "明天又要开会"))

        await manager.delete_memory(session, user.id, memory.id)
        assert await retrieve(session, user.id, "明天又要开会") == []


# ---------- 3. 未授权用户 ----------
async def test_unauthorized_user_blocked():
    from types import SimpleNamespace

    from app.bot.middlewares import AccessMiddleware

    settings = get_settings()
    mw = AccessMiddleware(settings)
    called = False

    async def handler(event, data):
        nonlocal called
        called = True
        return "ok"

    owner = settings.telegram_user_id
    assert owner is not None
    stranger = owner + 1

    assert await mw(handler, object(), {"event_from_user": SimpleNamespace(id=stranger)}) is None
    assert called is False

    assert await mw(handler, object(), {"event_from_user": SimpleNamespace(id=owner)}) == "ok"
    assert called is True


# ---------- 4. 敏感信息不自动入库 ----------
async def test_sensitive_info_never_auto_saved(db):
    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=5003)

    bot = FakeBot()
    llm = FakeLLM(
        '{"candidates":[{"category":"context","content":"他确诊了焦虑症，在吃药",'
        '"reason":"健康","sensitivity":"normal"}]}'
    )
    await run_memory_flow(
        bot=bot,
        settings=get_settings(),
        llm=llm,
        telegram_user_id=5003,
        user_text="我确诊了焦虑症，在吃药",
    )

    # 必须走确认，不能直接入库
    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 5003)
        assert await manager.list_memories(session, user.id) == []
        cands = await manager.pending_candidates(session, user.id)
        assert len(cands) == 1
        assert cands[0].sensitivity_level == "sensitive"


# ---------- 5. 候选不能绕过确认 ----------
async def test_candidate_cannot_bypass_confirmation(db):
    """正式记忆只能通过 save_memory / approve_candidate 产生；
    流水线对需要确认的候选只写 memory_candidates。"""
    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=5004)

    bot = FakeBot()
    llm = FakeLLM(
        '{"candidates":[{"category":"relationship","content":"他女朋友叫小雨",'
        '"person_name":"小雨","relation_type":"女朋友","reason":"亲密关系"}]}'
    )
    await run_memory_flow(
        bot=bot,
        settings=get_settings(),
        llm=llm,
        telegram_user_id=5004,
        user_text="我女朋友叫小雨",
    )

    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 5004)
        assert await manager.list_memories(session, user.id) == []
        from app.people import service as people_service

        assert await people_service.list_people(session, user.id) == []
        assert len(await manager.pending_candidates(session, user.id)) == 1


# ---------- 6. Webhook 密钥校验 ----------
async def test_webhook_rejects_wrong_secret(monkeypatch):
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "bot_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "s3cret")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        bad = await client.post(
            "/webhook/telegram",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert bad.status_code == 403

        missing = await client.post("/webhook/telegram", json={"update_id": 1})
        assert missing.status_code == 403


async def test_webhook_disabled_in_polling_mode(monkeypatch):
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "bot_mode", "polling")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/webhook/telegram", json={"update_id": 1})
        assert r.status_code == 404


async def test_webhook_requires_secret_configured(monkeypatch):
    from app.main import app

    settings = get_settings()
    monkeypatch.setattr(settings, "bot_mode", "webhook")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.post("/webhook/telegram", json={"update_id": 1})
        assert r.status_code == 503


# ---------- 7. 数据接口必须鉴权 ----------
async def test_api_requires_token(monkeypatch):
    from app.main import app

    settings = get_settings()
    transport = httpx.ASGITransport(app=app)

    # 未配置令牌 → 一律拒绝
    monkeypatch.setattr(settings, "admin_api_token", "")
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/api/v1/memories")).status_code == 401

    # 配置后：错令牌拒绝，对令牌放行
    monkeypatch.setattr(settings, "admin_api_token", "tok-123")
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (
            await client.get("/api/v1/memories", headers={"X-API-Token": "bad"})
        ).status_code == 401
        ok = await client.get("/api/v1/models", headers={"X-API-Token": "tok-123"})
        assert ok.status_code == 200
        assert "primary" in ok.json()


async def test_health_does_not_expose_data(db):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        r = await client.get("/health")
        body = r.text
        assert "memories_cache" not in body
        assert r.json()["config"]["telegram_configured"] in (True, False)
