"""
Handlers for item management.

Add flow (two ways to trigger):
  1. Button "➕ Додати оголошення"  — enters FSM state, asks for URL
  2. Paste any OLX URL in default state — auto-adds without extra step

Both paths scrape the title automatically via OLXScraper.
Manual /add command still works as an alias.
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import CallbackQuery, Message

from bot.keyboards import (
    cancel_keyboard,
    confirm_delete_keyboard,
    delete_keyboard,
    main_keyboard,
)
from bot.states import AddItem
from database.repository import Repository
from scraper.olx import OLXScraper

logger = logging.getLogger(__name__)
router = Router(name="items")

OLX_URL_RE = re.compile(r"https?://(?:www\.)?olx\.ua\S+", re.IGNORECASE)
DEFAULT_TITLE = "Оголошення OLX"

# ── Shared helper ─────────────────────────────────────────────────────────────


def _clean_title(raw: str) -> str:
    """Strip common OLX suffixes and whitespace from a scraped title."""
    for suffix in (" - OLX.ua", " — OLX.ua", " - OLX", " — OLX"):
        if suffix.lower() in raw.lower():
            raw = raw[: raw.lower().index(suffix.lower())]
    return raw.strip()[:200] or DEFAULT_TITLE


async def _scrape_title(url: str) -> str:
    """Fetch OLX listing page and return its title (or DEFAULT_TITLE on failure)."""
    try:
        async with OLXScraper() as scraper:
            result = await scraper.fetch_stats(url)
            if result.title:
                return _clean_title(result.title)
    except Exception as exc:
        logger.warning("Title scrape failed for %s: %s", url, exc)
    return DEFAULT_TITLE


async def _add_item_flow(
    message: Message,
    repo: Repository,
    url: str,
) -> None:
    """
    Core add logic used by both FSM and auto-detect flows:
      1. Send a 'loading' indicator.
      2. Scrape title from OLX.
      3. Persist to DB.
      4. Reply with result + main keyboard.
    """
    user = message.from_user
    if user is None:
        return

    await repo.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    # Show temporary "loading" message
    loading = await message.answer("🔍 Завантажую дані оголошення…")

    title = await _scrape_title(url)

    # Delete loading message (best-effort)
    try:
        await loading.delete()
    except Exception:
        pass

    item, created = await repo.add_item(
        user_id=user.id,
        olx_url=url,
        title=title,
    )

    if created:
        if title == DEFAULT_TITLE:
            note = "\n\n⚠️ Назву не вдалося розпізнати — встановлено типову."
        else:
            note = ""
        await message.answer(
            f"✅ <b>Додано до відстеження!</b>\n\n"
            f"📌 {item.title}{note}",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            f"ℹ️ Вже відстежується: <b>{item.title}</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )


# ── Flow entry: /add command or "➕" button ────────────────────────────────────


@router.message(StateFilter(default_state), Command("add"))
@router.message(StateFilter(default_state), F.text == "➕ Додати оголошення")
async def cmd_add(message: Message, state: FSMContext) -> None:
    """Prompt the user to paste an OLX URL and enter waiting state."""
    await state.set_state(AddItem.waiting_for_url)
    await message.answer(
        "📎 Надішліть посилання на OLX-оголошення\n\n"
        "<i>Приклад: https://www.olx.ua/d/uk/obyavlenie/…</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ── FSM state: waiting_for_url ────────────────────────────────────────────────


@router.message(StateFilter(AddItem.waiting_for_url), F.text == "🔙 Скасувати")
async def cancel_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("↩️ Скасовано.", reply_markup=main_keyboard())


@router.message(
    StateFilter(AddItem.waiting_for_url),
    F.text.regexp(r"(?i)https?://(?:www\.)?olx\.ua"),
)
async def process_url_in_state(
    message: Message, state: FSMContext, repo: Repository
) -> None:
    """Valid OLX URL received while in waiting state — scrape & add."""
    await state.clear()

    url_match = OLX_URL_RE.search(message.text or "")
    if not url_match:
        await message.answer("❌ Не вдалося розпізнати посилання.", reply_markup=main_keyboard())
        return

    await _add_item_flow(message, repo, url_match.group(0))


@router.message(StateFilter(AddItem.waiting_for_url))
async def process_non_url_in_state(message: Message) -> None:
    """Non-OLX text received in waiting state — nudge user."""
    await message.answer(
        "❓ Це не схоже на посилання OLX.\n\n"
        "Надішліть посилання виду <code>https://www.olx.ua/…</code>\n"
        "або натисніть <b>🔙 Скасувати</b>.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ── Auto-detect OLX URL in default state (paste-and-go) ──────────────────────


@router.message(
    StateFilter(default_state),
    F.text.regexp(r"(?i)https?://(?:www\.)?olx\.ua"),
)
async def auto_add_url(message: Message, repo: Repository) -> None:
    """User pastes an OLX URL without pressing any button — just add it."""
    url_match = OLX_URL_RE.search(message.text or "")
    if not url_match:
        return
    await _add_item_flow(message, repo, url_match.group(0))


# ── /list ─────────────────────────────────────────────────────────────────────


@router.message(Command("list"))
@router.message(F.text == "📋 Мої оголошення")
async def cmd_list(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer(
            "📋 Список порожній.\n\n"
            "Натисніть <b>➕ Додати оголошення</b> або вставте посилання OLX прямо сюди.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    lines = [f"📋 <b>Відстежувані оголошення ({len(items)}):</b>\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. <b>{item.title}</b>\n"
            f'   🔗 <a href="{item.olx_url}">посилання</a>  '
            f"🆔 <code>{item.id}</code>\n"
        )

    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=main_keyboard(),
    )


# ── /delete ───────────────────────────────────────────────────────────────────


@router.message(Command("delete"))
@router.message(F.text == "❌ Видалити")
async def cmd_delete(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer(
            "📋 Список порожній — нічого видаляти.",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer(
        "🗑 <b>Оберіть оголошення для видалення:</b>",
        reply_markup=delete_keyboard(items),
        parse_mode="HTML",
    )


# ── Delete inline callbacks ───────────────────────────────────────────────────


@router.callback_query(F.data.startswith("del:"))
async def cb_delete_select(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    assert callback.data is not None

    payload = callback.data.split(":", 1)[1]

    if payload == "cancel":
        await callback.message.edit_text("↩️ Видалення скасовано.")
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
        f"⚠️ Видалити <b>{item.title}</b>?\n\n<i>Ця дія незворотна.</i>",
        reply_markup=confirm_delete_keyboard(item.id, item.title),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("del_confirm:"))
async def cb_delete_confirm(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    assert callback.data is not None
    assert callback.from_user is not None

    try:
        item_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.message.edit_text("❌ Помилка: невірний ID.")
        return

    item = await repo.get_item_by_id(item_id)
    title = item.title if item else "невідоме"

    deleted = await repo.delete_item(item_id=item_id, user_id=callback.from_user.id)
    if deleted:
        await callback.message.edit_text(
            f"✅ <b>{title}</b> видалено з відстеження.",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            "❌ Не вдалося видалити. Можливо, оголошення вже видалено або не належить вам."
        )
