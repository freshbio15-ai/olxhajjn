"""
Inline keyboards for the bot.
"""

from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Item


def delete_keyboard(items: List[Item]) -> InlineKeyboardMarkup:
    """Return an inline keyboard with one button per item to delete."""
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {item.title[:40]}",
                callback_data=f"del:{item.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="❌ Скасувати", callback_data="del:cancel")
    )
    return builder.as_markup()


def confirm_delete_keyboard(item_id: int, title: str) -> InlineKeyboardMarkup:
    """Confirm deletion of a specific item."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Так, видалити",
            callback_data=f"del_confirm:{item_id}",
        ),
        InlineKeyboardButton(
            text="❌ Ні, залишити",
            callback_data="del:cancel",
        ),
    )
    return builder.as_markup()
