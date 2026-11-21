"""用真实模型验证 P6：人物关系候选 → 确认 → 自动归档到 people / relationships。

用法：python scripts/check_people.py（临时库，不影响 data/zhiwei.db）
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="zhiwei-ppl-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'check.db').as_posix()}"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.database.connection import get_session_factory, init_db  # noqa: E402
from app.llm.router import LLMRouter  # noqa: E402
from app.memory import manager  # noqa: E402
from app.memory.flow import run_memory_flow  # noqa: E402
from app.people import service as people  # noqa: E402
from app.profile.service import build_profile, render_profile_text  # noqa: E402
from app.services import user_service  # noqa: E402

SAMPLES = [
    "我妈下个月生日，我想给她买点东西",
    "我室友叫小林，在做后端",
]


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


async def main() -> None:
    settings = get_settings()
    await init_db()
    llm = LLMRouter(settings)

    async with get_session_factory()() as session:
        await user_service.get_or_create(session, telegram_id=1)

    for text in SAMPLES:
        bot = FakeBot()
        await run_memory_flow(
            bot=bot, settings=settings, llm=llm, telegram_user_id=1, user_text=text
        )
        print(f"\n用户：{text}")
        for msg in bot.sent:
            print("  →", msg.split("\n")[0])

    async with get_session_factory()() as session:
        user = await user_service.get_by_telegram_id(session, 1)
        cands = await manager.pending_candidates(session, user.id)
        rel_cands = [c for c in cands if c.category == "relationship"]
        print(f"\n待确认候选 {len(cands)} 条，其中关系类 {len(rel_cands)} 条：")
        for c in cands:
            print(f"  [{c.category}] {c.content} | person={c.person_name} rel={c.relation_type}")

        # 模拟用户点「保存」
        for c in rel_cands:
            await manager.approve_candidate(session, c)
            print(f"  已确认：{c.content}")

        print("\n=== 人物档案 ===")
        for person, rels in await people.list_people(session, user.id):
            rel_text = "、".join(r.relation_type for r in rels)
            print(f"  {person.name}（{rel_text}）：{person.description}")

        print("\n=== /profile 渲染 ===")
        grouped = await build_profile(session, user)
        print(render_profile_text(settings.user_name, grouped))


if __name__ == "__main__":
    asyncio.run(main())
