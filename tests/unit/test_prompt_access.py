"""人格提示词与访问控制测试。"""

from types import SimpleNamespace

from app.agent.prompts import build_system_prompt
from app.bot.middlewares import AccessMiddleware
from app.core.config import Settings


def test_prompt_contains_identity_and_rules():
    prompt = build_system_prompt(ai_name="知微", user_name="木川", memories=["他在学 AI"])
    assert "知微" in prompt
    assert "木川" in prompt
    assert "他在学 AI" in prompt
    # 七段结构都在
    for section in (
        "核心身份",
        "人格特点",
        "交流风格",
        "长期记忆使用规则",
        "隐私保护规则",
        "回复行为规范",
    ):
        assert section in prompt


def test_prompt_has_no_memory_placeholder_when_empty():
    prompt = build_system_prompt(ai_name="知微", user_name="木川", memories=[])
    assert "暂时还没有已确认的长期记忆" in prompt


def test_prompt_forbids_fake_human_life():
    prompt = build_system_prompt(ai_name="知微", user_name="木川")
    assert "不是人类" in prompt or "不能声称自己有真实的身体" in prompt


async def test_access_middleware_allows_owner():
    settings = Settings(telegram_user_id=42, llm_provider="ollama")
    mw = AccessMiddleware(settings)
    called = {}

    async def handler(event, data):
        called["ok"] = True
        return "done"

    result = await mw(handler, object(), {"event_from_user": SimpleNamespace(id=42)})
    assert result == "done"
    assert called["ok"] is True


async def test_access_middleware_blocks_stranger():
    settings = Settings(telegram_user_id=42, llm_provider="ollama")
    mw = AccessMiddleware(settings)
    called = {}

    async def handler(event, data):
        called["ok"] = True
        return "done"

    result = await mw(handler, object(), {"event_from_user": SimpleNamespace(id=999)})
    assert result is None
    assert "ok" not in called


async def test_access_middleware_blocks_when_owner_unset():
    settings = Settings(telegram_user_id=None, llm_provider="ollama")
    mw = AccessMiddleware(settings)

    async def handler(event, data):
        return "done"

    assert await mw(handler, object(), {"event_from_user": SimpleNamespace(id=42)}) is None
