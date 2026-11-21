"""Cloudflare Workers AI 适配器测试（用 httpx MockTransport，不真的发请求）。"""

from __future__ import annotations

import httpx
import pytest

from app.llm.base import LLMError
from app.llm.cloudflare import CloudflareProvider


def _provider(handler) -> CloudflareProvider:
    p = CloudflareProvider("tok", "acct-123", "@cf/meta/llama-3.1-8b-instruct")
    # 把内部 client 换成 mock
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class Patched(real_client):  # type: ignore[misc]
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    p._client_factory = Patched  # type: ignore[attr-defined]
    return p


async def test_success_parses_response(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"result": {"response": "你好呀"}, "success": True})

    p = _provider(handler)
    monkeypatch.setattr(httpx, "AsyncClient", p._client_factory)

    text = await p.chat([{"role": "user", "content": "hi"}])
    assert text == "你好呀"
    assert "acct-123" in seen["url"]
    assert seen["url"].endswith("/ai/run/@cf/meta/llama-3.1-8b-instruct")
    assert seen["auth"] == "Bearer tok"


async def test_rate_limit_raises(monkeypatch):
    p = _provider(lambda req: httpx.Response(429, json={"success": False}))
    monkeypatch.setattr(httpx, "AsyncClient", p._client_factory)
    with pytest.raises(LLMError, match="429"):
        await p.chat([{"role": "user", "content": "hi"}])


async def test_auth_error_raises(monkeypatch):
    p = _provider(lambda req: httpx.Response(401, json={"success": False}))
    monkeypatch.setattr(httpx, "AsyncClient", p._client_factory)
    with pytest.raises(LLMError, match="鉴权"):
        await p.chat([{"role": "user", "content": "hi"}])


async def test_empty_response_raises(monkeypatch):
    p = _provider(lambda req: httpx.Response(200, json={"result": {}, "success": True}))
    monkeypatch.setattr(httpx, "AsyncClient", p._client_factory)
    with pytest.raises(LLMError, match="空内容"):
        await p.chat([{"role": "user", "content": "hi"}])


def test_missing_account_id_rejected():
    with pytest.raises(LLMError, match="ACCOUNT_ID"):
        CloudflareProvider("tok", "")


def test_missing_token_rejected():
    with pytest.raises(LLMError, match="API_TOKEN"):
        CloudflareProvider("", "acct")


def test_router_builds_cloudflare_provider():
    from app.core.config import Settings
    from app.llm.router import build_provider

    s = Settings(
        llm_provider="cloudflare",
        cloudflare_api_token="tok",
        cloudflare_account_id="acct",
        telegram_user_id=1,
    )
    provider = build_provider("cloudflare", s)
    assert provider.name == "cloudflare"
    assert provider.account_id == "acct"
