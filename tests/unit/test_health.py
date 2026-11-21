"""P0 验收：应用能起来、健康检查通过、不泄露密钥。"""

import httpx
import pytest

from app.core.config import get_settings
from app.database.connection import dispose_db, init_db
from app.main import app


@pytest.fixture
async def client():
    await init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await dispose_db()


async def test_root_returns_service_info(client):
    r = await client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"].startswith("知微")
    assert body["version"] == "0.1.0"


async def test_health_ok_and_db_connected(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["config"]["database"] == "sqlite"
    assert "users" in body["stats"]
    assert "memories" in body["stats"]


async def test_health_never_leaks_secrets(client):
    r = await client.get("/health")
    raw = r.text
    assert "TEST-TOKEN-SHOULD-NOT-LEAK" not in raw
    assert "telegram_bot_token" not in raw.lower()


def test_settings_public_dict_has_no_secrets():
    settings = get_settings()
    public = settings.public_dict()
    dumped = str(public)
    assert settings.telegram_bot_token not in dumped
    assert "api_key" not in dumped.lower()
    assert public["telegram_configured"] is True
    assert public["owner_bound"] is True


def test_owner_id_parsed_as_int():
    assert get_settings().telegram_user_id == 123456789
