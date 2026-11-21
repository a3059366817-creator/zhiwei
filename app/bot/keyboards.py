"""Inline 键盘。"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reminder_actions(reminder_id: str) -> InlineKeyboardMarkup:
    """提醒卡片上的按钮。callback_data 上限 64 字节，UUID 36 字符刚好够。"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ 完成了", callback_data=f"rem:done:{reminder_id}"),
                InlineKeyboardButton(
                    text="⏰ 20 分钟后", callback_data=f"rem:snooze:{reminder_id}"
                ),
            ]
        ]
    )


def reminder_list(rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """待办列表：每条一个「完成」按钮。rows = [(id, 标题)]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ {title[:28]}", callback_data=f"rem:done:{rid}")]
            for rid, title in rows[:8]
        ]
    )


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="新会话", callback_data="cmd:new"),
                InlineKeyboardButton(text="我的记忆", callback_data="cmd:memory"),
            ],
            [
                InlineKeyboardButton(text="历史", callback_data="cmd:history"),
                InlineKeyboardButton(text="当前模型", callback_data="cmd:model"),
            ],
        ]
    )


def memory_candidate(
    candidate_id: str,
) -> InlineKeyboardMarkup:
    """记忆候选的确认按钮（P5 使用）。"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ 保存", callback_data=f"mem:save:{candidate_id}"),
                InlineKeyboardButton(text="✏️ 修改", callback_data=f"mem:edit:{candidate_id}"),
            ],
            [
                InlineKeyboardButton(text="⏸ 暂不保存", callback_data=f"mem:skip:{candidate_id}"),
                InlineKeyboardButton(
                    text="🚫 以后别问这条", callback_data=f"mem:never:{candidate_id}"
                ),
            ],
        ]
    )


def memory_list(rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """记忆列表：每条两个按钮（改 / 删）。rows = [(id, 内容摘要)]"""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✏️ {title[:28]}", callback_data=f"mem:edit:{mid}"),
                InlineKeyboardButton(text="🗑", callback_data=f"mem:del:{mid}"),
            ]
            for mid, title in rows
        ]
    )


def people_list(rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """人物列表：每个人可改称呼、改备注、改关系、删除。rows = [(id, 名字)]"""
    keyboard: list[list[InlineKeyboardButton]] = []
    for pid, name in rows:
        keyboard.append(
            [
                InlineKeyboardButton(text=f"✏️ {name[:20]}", callback_data=f"ppl:name:{pid}"),
                InlineKeyboardButton(text="📝", callback_data=f"ppl:desc:{pid}"),
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(text="🔗 改关系", callback_data=f"ppl:rel:{pid}"),
                InlineKeyboardButton(text="🗑 删除", callback_data=f"ppl:del:{pid}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
