"""从模型回复里解析提醒控制标签。

约定（与旧 Node 版一致，模型已验证能稳定输出）：
    [[TODO:交周报|2026-11-22T09:00]]   新建提醒（带时间）
    [[TODO:买牛奶]]                    新建待办（不带时间）
    [[DONE:3]] 或 [[DONE:交周报]]      完成某条

标签必须从最终发给用户的文本里剥掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

TODO_RE = re.compile(r"\[\[\s*TODO\s*[:：]\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]", re.I)
DONE_RE = re.compile(r"\[\[\s*DONE\s*[:：]\s*([^\]]+?)\s*\]\]", re.I)
STRAY_RE = re.compile(r"^\s*(TODO|DONE)\s*[:：].*$", re.I | re.M)


@dataclass
class ParsedActions:
    text: str
    todos: list[tuple[str, datetime | None]] = field(default_factory=list)
    done: list[str] = field(default_factory=list)


def parse_local_datetime(raw: str) -> datetime | None:
    """解析 'YYYY-MM-DDTHH:mm'（无时区，按本地时间处理）。"""
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def parse_actions(raw: str) -> ParsedActions:
    text = str(raw or "")

    todos: list[tuple[str, datetime | None]] = []
    for m in TODO_RE.finditer(text):
        title = m.group(1).strip()
        due = parse_local_datetime(m.group(2)) if m.group(2) else None
        if title:
            todos.append((title, due))
    text = TODO_RE.sub("", text)

    done = [m.group(1).strip() for m in DONE_RE.finditer(text) if m.group(1).strip()]
    text = DONE_RE.sub("", text)

    text = STRAY_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ParsedActions(text=text, todos=todos, done=done)
