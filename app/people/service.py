"""人物档案与关系。

规格 3.2C：只记录用户主动介绍的人，且必须保留信息来源；
确认后的关系才进入这里，模型不能直接写。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Person, Relationship, User

logger = logging.getLogger(__name__)


def _norm(name: str) -> str:
    return re.sub(r"[\s\W_]+", "", name or "").lower()


async def find_person(session: AsyncSession, user_id: str, name: str) -> Person | None:
    target = _norm(name)
    if not target:
        return None
    rows = await session.scalars(select(Person).where(Person.user_id == user_id))
    for p in rows:
        if _norm(p.name) == target:
            return p
    return None


async def upsert_person(
    session: AsyncSession, user: User, name: str, description: str | None = None
) -> Person:
    person = await find_person(session, user.id, name)
    if person is None:
        person = Person(user_id=user.id, name=name.strip(), description=description)
        session.add(person)
        await session.commit()
        await session.refresh(person)
        logger.info("人物档案已建立：%s", person.name)
        return person
    if description and not person.description:
        person.description = description
        await session.commit()
        await session.refresh(person)
    return person


async def add_relationship(
    session: AsyncSession,
    user: User,
    person: Person,
    relation_type: str,
    description: str | None = None,
    source_message_id: str | None = None,
) -> Relationship:
    """同一人物 + 同一关系类型只保留一条，避免重复。"""
    existing = await session.scalar(
        select(Relationship).where(
            Relationship.user_id == user.id,
            Relationship.person_id == person.id,
            Relationship.relation_type == relation_type,
        )
    )
    if existing is not None:
        if description and existing.description != description:
            existing.description = description
            await session.commit()
            await session.refresh(existing)
        return existing

    rel = Relationship(
        user_id=user.id,
        person_id=person.id,
        relation_type=relation_type,
        description=description,
        source_message_id=source_message_id,
    )
    session.add(rel)
    await session.commit()
    await session.refresh(rel)
    return rel


async def list_people(
    session: AsyncSession, user_id: str, limit: int = 30
) -> list[tuple[Person, list[Relationship]]]:
    people = list(
        await session.scalars(
            select(Person)
            .where(Person.user_id == user_id)
            .order_by(desc(Person.updated_at))
            .limit(limit)
        )
    )
    out: list[tuple[Person, list[Relationship]]] = []
    for p in people:
        rels = list(
            await session.scalars(select(Relationship).where(Relationship.person_id == p.id))
        )
        out.append((p, rels))
    return out


async def get_person(session: AsyncSession, user_id: str, person_id: str) -> Person | None:
    return await session.scalar(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )


async def relations_of(session: AsyncSession, person_id: str) -> list[Relationship]:
    return list(
        await session.scalars(select(Relationship).where(Relationship.person_id == person_id))
    )


async def update_person(
    session: AsyncSession,
    user_id: str,
    person_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Person | None:
    """改称呼或备注。改名时若与已有档案重名，会合并到那一条。"""
    person = await get_person(session, user_id, person_id)
    if person is None:
        return None

    if name is not None:
        new_name = name.strip()
        if new_name:
            clash = await find_person(session, user_id, new_name)
            if clash is not None and clash.id != person.id:
                # 合并：把关系挪到已有档案，再删掉旧的
                for rel in await relations_of(session, person.id):
                    rel.person_id = clash.id
                await session.execute(delete(Person).where(Person.id == person.id))
                await session.commit()
                return clash
            person.name = new_name

    if description is not None:
        person.description = description.strip() or None

    await session.commit()
    await session.refresh(person)
    logger.info("人物档案已更新：%s", person.name)
    return person


async def set_relation(
    session: AsyncSession, user: User, person: Person, relation_type: str
) -> Relationship:
    """把某个人的关系改成指定类型（只保留一条）。"""
    await session.execute(delete(Relationship).where(Relationship.person_id == person.id))
    rel = Relationship(
        user_id=user.id,
        person_id=person.id,
        relation_type=relation_type.strip(),
        description=person.description,
    )
    session.add(rel)
    await session.commit()
    await session.refresh(rel)
    return rel


async def delete_person(session: AsyncSession, user_id: str, person_id: str) -> bool:
    person = await get_person(session, user_id, person_id)
    if person is None:
        return False
    await session.execute(delete(Relationship).where(Relationship.person_id == person_id))
    await session.execute(delete(Person).where(Person.id == person_id))
    await session.commit()
    logger.info("人物档案已删除：%s", person.name)
    return True


KINSHIP = set("爸妈哥姐弟妹爷奶叔姨舅姑")

def _aliases(name: str) -> set[str]:
    """用户可能用简称（妈妈→妈、小林→小林/林、王老师→王）。"""
    n = (name or "").strip()
    if not n:
        return set()
    out = {n}
    stripped = n.lstrip("小老阿")
    if stripped != n and len(stripped) >= 2:
        out.add(stripped)
    if len(n) == 2 and n[0] == n[1] and n[0] in KINSHIP:
        out.add(n[0])
    for suf in ("老师", "同学", "先生", "女士", "医生"):
        if n.endswith(suf) and len(n) > len(suf):
            out.add(n[: -len(suf)])
    return out


async def people_context(
    session: AsyncSession, user_id: str, query: str, limit: int = 3
) -> list[str]:
    """只把「当前这句话里提到的人」注入上下文，避免无谓的隐私扩散。"""
    rows = await list_people(session, user_id, limit=50)
    hits: list[str] = []
    for person, rels in rows:
        if not any(alias in query for alias in _aliases(person.name)):
            continue
        rel_text = "、".join(r.relation_type for r in rels) or "关系未记录"
        detail = f"{person.name}（{rel_text}）"
        if person.description:
            detail += f"：{person.description}"
        hits.append(detail)
        if len(hits) >= limit:
            break
    return hits
