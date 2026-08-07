"""
Handlers for item management: /add, /list, /delete.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards import confirm_delete_keyboard, delete_keyboard
from database.repository import Repository

logger = logging.getLogger(__name__)
router = Router(name="items")


# ── /add ─────────────────────────────────────────────────────────────────────


@router.message(Command("add"))
async def cmd_add(message: Message, repo: Repository) -> None:
    """Usage: /add <title> <olx_url>"""
    user = message.from_user
    if user is None:
        return

    # Ensure user exists in DB
    await repo.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❗ Формат: <code>/add &lt;назва&gt; &lt;посилання_olx&gt;</code>\n\n"
            "Приклад:\n"
            "<code>/add Мій товар https://www.olx.ua/d/uk/...</code>",
            parse_mode="HTML",
        )
        return

    _, title, olx_url = args[0], args[1], args[2]

    if "olx.ua" not in olx_url:
        await message.answer("❌ Посилання має бути з <b>olx.ua</b>.", parse_mode="HTML")
        return

    item, created = await repo.add_item(
        user_id=user.id,
        olx_url=olx_url.strip(),
        title=title.strip(),
    )

    if created:
        await message.answer(
            f"✅ Оголошення <b>{item.title}</b> додано до відстеження!\n"
            "Перша перевірка відбудеться під час наступного запланованого циклу.",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"ℹ️ Оголошення <b>{item.title}</b> вже відстежується.",
            parse_mode="HTML",
        )


# ── /list ─────────────────────────────────────────────────────────────────────


@router.message(Command("list"))
async def cmd_list(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer(
            "📋 Список порожній.\n"
            "Додайте оголошення командою /add &lt;назва&gt; &lt;посилання&gt;",
            parse_mode="HTML",
        )
        return

    lines = ["📋 <b>Відстежувані оголошення:</b>\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. <b>{item.title}</b>\n"
            f"   🔗 <a href=\"{item.olx_url}\">посилання</a>\n"
            f"   🆔 ID: <code>{item.id}</code>\n"
        )

    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


# ── /delete ───────────────────────────────────────────────────────────────────


@router.message(Command("delete"))
async def cmd_delete(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer("📋 Список оголошень порожній.")
        return

    await message.answer(
        "🗑 <b>Оберіть оголошення для видалення:</b>",
        reply_markup=delete_keyboard(items),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("del:"))
async def cb_delete_select(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    assert callback.data is not None

    payload = callback.data.split(":", 1)[1]

    if payload == "cancel":
        await callback.message.edit_text("❌ Видалення скасовано.")
        return

    try:
        item_id = int(payload)
    except ValueError:
        await callback.message.edit_text("❌ Помилка: невірний ID.")
        return

    item = await repo.get_item_by_id(item_id)
    if not item:
        await callback.message.edit_text("❌ Оголошення не знайдено.")
        return

    await callback.message.edit_text(
        f"⚠️ Видалити <b>{item.title}</b>?\n\nЦя дія незворотна.",
        reply_markup=confirm_delete_keyboard(item.id, item.title),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("del_confirm:"))
async def cb_delete_confirm(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    assert callback.data is not None
    assert callback.from_user is not None

    payload = callback.data.split(":", 1)[1]
    try:
        item_id = int(payload)
    except ValueError:
        await callback.message.edit_text("❌ Помилка: невірний ID.")
        return

    item = await repo.get_item_by_id(item_id)
    title = item.title if item else "невідоме"

    deleted = await repo.delete_item(item_id=item_id, user_id=callback.from_user.id)
    if deleted:
        await callback.message.edit_text(
            f"✅ Оголошення <b>{title}</b> видалено з відстеження.",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "❌ Не вдалося видалити. Можливо, оголошення вже видалено або не належить вам."
        )
