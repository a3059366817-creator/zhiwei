"""消息分片等小工具。"""

from __future__ import annotations

from aiogram.types import Message

TG_LIMIT = 4000


def split_text(text: str, limit: int = TG_LIMIT) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit * 0.6:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


async def answer_long(message: Message, text: str) -> None:
    for chunk in split_text(text):
        await message.answer(chunk)
