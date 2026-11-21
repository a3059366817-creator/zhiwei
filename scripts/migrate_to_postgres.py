"""把本地 SQLite 数据搬到 Postgres（Neon）。

用法：python scripts/migrate_to_postgres.py
- 按外键顺序复制，保留原 id 与时间戳
- 目标已有同 id 记录时跳过（可重复执行）
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import UTC, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.database.models import (  # noqa: E402
    Conversation,
    Memory,
    MemoryCandidate,
    Message,
    Person,
    Relationship,
    User,
    UserSettings,
)

SQLITE_URL = "sqlite+aiosqlite:///./data/zhiwei.db"

# 外键依赖顺序
MODELS = [
    User,
    Conversation,
    Message,
    Memory,
    MemoryCandidate,
    Person,
    Relationship,
    UserSettings,
]


def _aware(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def main() -> None:
    settings = get_settings()
    if settings.is_sqlite:
        print("DATABASE_URL 还是 SQLite，请先改成 Postgres")
        return

    src_engine = create_async_engine(SQLITE_URL)
    dst_engine = create_async_engine(settings.database_url, connect_args={"timeout": 20})
    Src = async_sessionmaker(src_engine, expire_on_commit=False)
    Dst = async_sessionmaker(dst_engine, expire_on_commit=False)

    total = 0
    async with Src() as s, Dst() as d:
        for model in MODELS:
            rows = (await s.scalars(select(model))).all()
            if not rows:
                print(f"{model.__tablename__:20s} 0 条（跳过）")
                continue

            pk = model.__table__.primary_key.columns.values()[0].name
            existing = set((await d.scalars(select(getattr(model, pk)))).all())
            copied = 0
            for row in rows:
                if getattr(row, pk) in existing:
                    continue
                data = {c.name: _aware(getattr(row, c.name)) for c in model.__table__.columns}
                d.add(model(**data))
                copied += 1
            await d.commit()
            total += copied
            print(f"{model.__tablename__:20s} {len(rows)} 条 → 新写入 {copied} 条")

    await src_engine.dispose()
    await dst_engine.dispose()
    print(f"\n完成，共写入 {total} 条。")

    # 复核
    check_engine = create_async_engine(settings.database_url)
    Check = async_sessionmaker(check_engine, expire_on_commit=False)
    async with Check() as c:
        for model in MODELS:
            n = len((await c.scalars(select(model))).all())
            print(f"  {model.__tablename__:20s} {n}")
    await check_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
