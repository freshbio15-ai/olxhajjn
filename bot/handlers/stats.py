"""
/stats handler — shows current statistics with delta vs previous snapshot.
Responds to both /stats command and "📊 Статистика" keyboard button.
"""

from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.keyboards import main_keyboard
from database.models import Stat
from database.repository import Repository

router = Router(name="stats")


def _delta(current: int, previous: Optional[int]) -> str:
    if previous is None:
        return ""
    diff = current - previous
    if diff > 0:
        return f" <b>(+{diff})</b>"
    if diff < 0:
        return f" <i>({diff})</i>"
    return " <i>(±0)</i>"


def _format_stat_block(
    title: str,
    url: str,
    latest: Optional[Stat],
    previous: Optional[Stat],
) -> str:
    if latest is None:
        return (
            f'📌 <b>{title}</b>\n'
            f'   🔗 <a href="{url}">посилання</a>\n'
            f"   ⏳ Дані ще не зібрано — зачекайте наступної перевірки.\n"
        )

    pv = previous.views_count if previous else None
    pf = previous.favorites_count if previous else None
    pp = previous.phone_clicks_count if previous else None
    ts = latest.timestamp.strftime("%d.%m.%Y %H:%M") if latest.timestamp else "—"

    return (
        f'📌 <b>{title}</b>\n'
        f'   🔗 <a href="{url}">посилання</a>\n'
        f"   👁 Перегляди: <code>{latest.views_count}</code>{_delta(latest.views_count, pv)}\n"
        f"   ⭐ Обране: <code>{latest.favorites_count}</code>{_delta(latest.favorites_count, pf)}\n"
        f"   📞 Кліки на телефон: <code>{latest.phone_clicks_count}</code>{_delta(latest.phone_clicks_count, pp)}\n"
        f"   🕐 Оновлено: {ts}\n"
    )


@router.message(Command("stats"))
@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer(
            "📊 Список порожній.\n\n"
            "Натисніть <b>➕ Додати оголошення</b> або вставте посилання OLX.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    blocks = [f"📊 <b>Статистика ({len(items)} оголошень):</b>\n"]
    for item in items:
        latest = await repo.get_latest_stat(item.id)
        previous = await repo.get_previous_stat(item.id)
        blocks.append(_format_stat_block(item.title, item.olx_url, latest, previous))

    await message.answer(
        "\n".join(blocks),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=main_keyboard(),
    )
