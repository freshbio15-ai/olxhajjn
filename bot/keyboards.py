"""
Keyboards — both persistent Reply keyboard and inline keyboards.
"""

from __future__ import annotations

from typing import List

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.models import Item


# ── Reply (persistent) keyboards ──────────────────────────────────────────────

def main_keyboard() -> ReplyKeyboardMarkup:
    """Primary keyboard shown at the bottom of the chat at all times."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="➕ Додати оголошення"),
                KeyboardButton(text="📋 Мої оголошення"),
            ],
            [
                KeyboardButton(text="📊 Статистика"),
                KeyboardButton(text="❌ Видалити"),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="Оберіть дію або вставте OLX-посилання…",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    """Shown while waiting for a URL — lets the user abort the flow."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Скасувати")]],
        resize_keyboard=True,
        input_field_placeholder="Вставте посилання на OLX-оголошення…",
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


# ── Inline keyboards ───────────────────────────────────────────────────────────

def delete_keyboard(items: List[Item]) -> InlineKeyboardMarkup:
    """One inline button per item to select for deletion."""
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
    """Confirm / reject deletion of a specific item."""
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
