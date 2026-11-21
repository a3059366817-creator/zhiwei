"""进程内的「等待用户输入新内容」状态。

单用户场景（规格 V1.0 只允许一个 Telegram 用户），用内存字典足够。
一次只保留一个待编辑目标，避免状态混乱。
"""

from __future__ import annotations

from dataclasses import dataclass

# kind 取值：
#   candidate    —— 修改待确认候选的内容
#   memory       —— 修改已入库记忆的内容（即「替换」）
#   person_name  —— 修改人物称呼
#   person_desc  —— 修改人物备注/关系描述
#   relation     —— 修改关系类型（extra 存 person_id）
_PENDING: dict[int, PendingEdit] = {}


@dataclass(frozen=True)
class PendingEdit:
    kind: str
    target_id: str
    extra: str | None = None


def set_edit(user_id: int, kind: str, target_id: str, extra: str | None = None) -> None:
    _PENDING[user_id] = PendingEdit(kind, target_id, extra)


def pop_edit(user_id: int) -> PendingEdit | None:
    return _PENDING.pop(user_id, None)


def peek_edit(user_id: int) -> PendingEdit | None:
    return _PENDING.get(user_id)


def clear(user_id: int) -> None:
    _PENDING.pop(user_id, None)
