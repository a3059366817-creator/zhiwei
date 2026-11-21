"""用真实模型跑一遍记忆流水线，检查抽取质量与规则判定。

用法：python scripts/check_memory.py
（用临时数据库，不会污染 data/zhiwei.db）
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="zhiwei-mem-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'check.db').as_posix()}"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.database.connection import get_session_factory, init_db  # noqa: E402
from app.llm.router import LLMRouter  # noqa: E402
from app.memory import manager  # noqa: E402
from app.memory.flow import run_memory_flow  # noqa: E402
from app.services import user_service  # noqa: E402

SAMPLES = [
    "我最近在用 Python 写一个 AI 助手，后端是 FastAPI",
    "我每天早上都要喝一杯冰美式",
    "我妈下个月生日，我想给她买个东西",
    "我工资一万二左右",
    "我的银行卡密码是 abc123",
    "今天天气不错",
]


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


async def main() -> None:
    settings = get_settings()
    llm = LLMRouter(settings)
    await init_db()

    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=1)

    for text in SAMPLES:
        bot = FakeBot()
        await run_memory_flow(
            bot=bot,
            settings=settings,
            llm=llm,
            telegram_user_id=1,
            user_text=text,
        )
        print(f"\n用户：{text}")
        if not bot.sent:
            print("  → 没记住任何东西")
        for msg in bot.sent:
            first = msg.split("\n")[0]
            kind = "自动保存" if "记下了" in msg else "请求确认"
            print(f"  → [{kind}] {first}")

    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 1)
        mems = await manager.list_memories(session, user.id)
        cands = await manager.pending_candidates(session, user.id)
        print(f"\n=== 结果：正式记忆 {len(mems)} 条，待确认 {len(cands)} 条 ===")
        for m in mems:
            print(f"  [记忆][{m.category}] {m.content}")
        for c in cands:
            print(f"  [候选][{c.category}/{c.sensitivity_level}] {c.content}")


if __name__ == "__main__":
    asyncio.run(main())
