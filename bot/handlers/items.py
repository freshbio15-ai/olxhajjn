"""
Handlers for item management.

Add flow (two-step FSM):
  Step 1 — User sends OLX URL  →  bot saves URL to FSM data, asks for title
  Step 2 — User types name      →  bot adds item, immediately scrapes stats, shows result

Trigger options:
  • Button "➕ Додати оголошення" → prompts for URL (FSM step 1)
  • Paste any OLX URL directly   → skips to step 2 (ask for title)
  • /add command                 → same as button
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
from database.models import async_session as new_session
from database.repository import Repository
from scraper.olx import OLXScraper

logger = logging.getLogger(__name__)
router = Router(name="items")

OLX_URL_RE = re.compile(r"https?://(?:www\.)?olx\.ua\S+", re.IGNORECASE)


# ── Shared helpers ────────────────────────────────────────────────────────────


async def _force_scrape_and_save(item_id: int, url: str) -> str:
    """
    Scrapes OLX stats and persists them in an INDEPENDENT session with
    its own immediate commit — completely decoupled from the handler's
    middleware session so the snapshot is guaranteed to be in the DB.
    """
    try:
        async with OLXScraper() as scraper:
            result = await scraper.fetch_stats(url)

        if result.success:
            # Own session → own commit → no dependency on middleware timing
            async with new_session() as session:
                repo = Repository(session)
                await repo.save_stat(
                    item_id=item_id,
                    views=result.views,
                    favorites=result.favorites,
                    phone_clicks=result.phone_clicks,
                )
                await session.commit()

            return (
                f"\n\n📊 <b>Перша статистика:</b>\n"
                f"   👁 Перегляди: <code>{result.views}</code>\n"
                f"   ⭐ Обране: <code>{result.favorites}</code>\n"
                f"   📞 Кліки на телефон: <code>{result.phone_clicks}</code>"
            )
        else:
            logger.warning("Force scrape failed for item %d: %s", item_id, result.error)
            return (
                f"\n\n⚠️ OLX не дав статистику ({result.error}).\n"
                "Перша статистика прийде при наступній перевірці (до 2 год)."
            )

    except Exception as exc:
        logger.warning("Force scrape exception for item %d: %s", item_id, exc)
        return (
            "\n\n⚠️ Не вдалось завантажити статистику.\n"
            "Перша статистика прийде при наступній перевірці (до 2 год)."
        )


async def _finalize_add(
    message: Message,
    repo: Repository,
    url: str,
    title: str,
) -> None:
    """
    Persist item → commit immediately → scrape stats in own session → reply.
    """
    user = message.from_user
    if user is None:
        return

    await repo.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    item, created = await repo.add_item(
        user_id=user.id,
        olx_url=url,
        title=title.strip()[:200],
    )

    if not created:
        await message.answer(
            f"ℹ️ Вже відстежується: <b>{item.title}</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    # ── Commit the item IMMEDIATELY so FK is valid for the stat insert ────────
    await repo._s.commit()

    # ── Scrape stats in a separate session with its own commit ─────────────────
    loading = await message.answer("🔍 Завантажую першу статистику…")
    stats_text = await _force_scrape_and_save(item.id, url)
    try:
        await loading.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ <b>Оголошення додано!</b>\n\n"
        f"📌 {item.title}{stats_text}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ── Step 1 entry: /add command or "➕" button ──────────────────────────────────


@router.message(StateFilter(default_state), Command("add"))
@router.message(StateFilter(default_state), F.text == "➕ Додати оголошення")
async def cmd_add(message: Message, state: FSMContext) -> None:
    """Prompt for OLX URL and enter FSM step 1."""
    await state.set_state(AddItem.waiting_for_url)
    await message.answer(
        "📎 <b>Крок 1/2</b> — Надішліть посилання на OLX-оголошення:\n\n"
        "<i>Приклад: https://www.olx.ua/d/uk/obyavlenie/…</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ── FSM step 1: waiting_for_url ───────────────────────────────────────────────


@router.message(StateFilter(AddItem.waiting_for_url), F.text == "🔙 Скасувати")
async def cancel_from_url(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("↩️ Скасовано.", reply_markup=main_keyboard())


@router.message(
    StateFilter(AddItem.waiting_for_url),
    F.text.regexp(r"(?i)https?://(?:www\.)?olx\.ua"),
)
async def got_url_in_state(message: Message, state: FSMContext) -> None:
    """Valid OLX URL received → save it, move to step 2 (ask for title)."""
    url_match = OLX_URL_RE.search(message.text or "")
    if not url_match:
        await message.answer("❌ Не вдалося розпізнати посилання.", reply_markup=main_keyboard())
        await state.clear()
        return

    await state.update_data(url=url_match.group(0))
    await state.set_state(AddItem.waiting_for_title)
    await message.answer(
        "✏️ <b>Крок 2/2</b> — Введіть назву для цього оголошення:\n\n"
        "<i>Наприклад: Колаген 450г, Rayban Meta…</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.message(StateFilter(AddItem.waiting_for_url))
async def bad_url_in_state(message: Message) -> None:
    """Non-URL text while waiting for URL — nudge user."""
    await message.answer(
        "❓ Це не схоже на посилання OLX.\n\n"
        "Надішліть посилання виду <code>https://www.olx.ua/…</code>\n"
        "або натисніть <b>🔙 Скасувати</b>.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


# ── FSM step 2: waiting_for_title ─────────────────────────────────────────────


@router.message(StateFilter(AddItem.waiting_for_title), F.text == "🔙 Скасувати")
async def cancel_from_title(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("↩️ Скасовано.", reply_markup=main_keyboard())


@router.message(StateFilter(AddItem.waiting_for_title))
async def got_title_in_state(
    message: Message, state: FSMContext, repo: Repository
) -> None:
    """User typed a title → finalize: save item + scrape stats immediately."""
    data = await state.get_data()
    url: str = data.get("url", "")
    title = (message.text or "").strip()

    # Guard: user typed a URL instead of a name — don't clear state, ask again
    if title.startswith("http") or "olx.ua" in title:
        await message.answer(
            "⚠️ Це посилання, а не назва!\n\n"
            "✏️ Введіть коротку <b>назву</b> для оголошення:\n"
            "<i>Наприклад: Колаген, Rayban Meta, Gymshark…</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
        return

    await state.clear()

    if not title:
        await message.answer("❌ Назва не може бути порожньою.", reply_markup=main_keyboard())
        return

    if not url:
        await message.answer("❌ Посилання втрачено. Спробуйте знову.", reply_markup=main_keyboard())
        return

    await _finalize_add(message, repo, url, title)


# ── Auto-detect OLX URL pasted in default state ───────────────────────────────


@router.message(
    StateFilter(default_state),
    F.text.regexp(r"(?i)https?://(?:www\.)?olx\.ua"),
)
async def auto_detect_url(message: Message, state: FSMContext) -> None:
    """User pastes OLX URL directly → skip to step 2 (ask for title)."""
    url_match = OLX_URL_RE.search(message.text or "")
    if not url_match:
        return

    await state.update_data(url=url_match.group(0))
    await state.set_state(AddItem.waiting_for_title)
    await message.answer(
        "✏️ Введіть назву для цього оголошення:\n\n"
        "<i>Наприклад: Колаген 450г, Rayban Meta…</i>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


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
            "Натисніть <b>➕ Додати оголошення</b> або вставте посилання OLX.",
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
        await message.answer("📋 Список порожній — нічого видаляти.", reply_markup=main_keyboard())
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
            f"✅ <b>{title}</b> видалено з відстеження.", parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            "❌ Не вдалося видалити. Можливо, оголошення вже видалено або не належить вам."
        )
