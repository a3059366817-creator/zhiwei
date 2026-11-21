"""模型路由测试：主模型失败要能自动切备用。"""

import pytest

from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.router import LLMRouter, build_provider


class _OkProvider:
    name = "ok"

    async def chat(self, messages, *, temperature=0.8, max_tokens=None):
        return "备用模型的回复"


class _FailProvider:
    name = "fail"

    async def chat(self, messages, *, temperature=0.8, max_tokens=None):
        raise LLMError("模拟超时")


def _settings(**kw) -> Settings:
    base = {
        "llm_provider": "ollama",
        "llm_fallback_provider": "",
        "telegram_user_id": 1,
    }
    base.update(kw)
    return Settings(**base)


async def test_fallback_when_primary_fails(monkeypatch):
    router = LLMRouter(_settings())
    router._providers = [_FailProvider(), _OkProvider()]

    text, model = await router.chat([{"role": "user", "content": "hi"}])
    assert text == "备用模型的回复"
    assert model == "ok"


async def test_all_providers_fail_raises():
    router = LLMRouter(_settings())
    router._providers = [_FailProvider()]

    with pytest.raises(LLMError):
        await router.chat([{"role": "user", "content": "hi"}])


async def test_no_provider_raises():
    router = LLMRouter(_settings())
    router._providers = []
    with pytest.raises(LLMError):
        await router.chat([{"role": "user", "content": "hi"}])


def test_gemini_without_key_is_skipped():
    settings = _settings(llm_provider="gemini", gemini_api_key="")
    router = LLMRouter(settings)
    # 没 key 时不该把 gemini 加进可用列表
    assert "gemini" not in router.provider_names


def test_unknown_provider_raises():
    with pytest.raises(LLMError):
        build_provider("nope", _settings())
