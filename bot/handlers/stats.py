"""
/stats handler — shows current statistics with delta vs previous snapshot.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from database.models import Stat
from database.repository import Repository

logger = logging.getLogger(__name__)
router = Router(name="stats")


def _delta(current: int, previous: Optional[int]) -> str:
    if previous is None:
        return ""
    diff = current - previous
    if diff > 0:
        return f" <b>(+{diff})</b>"
    if diff < 0:
        return f" <i>({diff})</i>"
    return " (±0)"


def format_stat_block(
    item_title: str,
    item_url: str,
    latest: Optional[Stat],
    previous: Optional[Stat],
) -> str:
    if latest is None:
        return (
            f"📌 <b>{item_title}</b>\n"
            f"   🔗 <a href=\"{item_url}\">посилання</a>\n"
            f"   ⏳ Ще не перевірялось\n"
        )

    prev_views = previous.views_count if previous else None
    prev_fav = previous.favorites_count if previous else None
    prev_ph = previous.phone_clicks_count if previous else None

    ts = latest.timestamp.strftime("%d.%m.%Y %H:%M") if latest.timestamp else "—"

    return (
        f"📌 <b>{item_title}</b>\n"
        f"   🔗 <a href=\"{item_url}\">посилання</a>\n"
        f"   👁 Перегляди: <code>{latest.views_count}</code>"
        f"{_delta(latest.views_count, prev_views)}\n"
        f"   ⭐ Обране: <code>{latest.favorites_count}</code>"
        f"{_delta(latest.favorites_count, prev_fav)}\n"
        f"   📞 Кліки на телефон: <code>{latest.phone_clicks_count}</code>"
        f"{_delta(latest.phone_clicks_count, prev_ph)}\n"
        f"   🕐 Оновлено: {ts}\n"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    items = await repo.get_items_by_user(user.id)
    if not items:
        await message.answer(
            "📊 Список оголошень порожній.\n"
            "Додайте оголошення командою /add &lt;назва&gt; &lt;посилання&gt;",
            parse_mode="HTML",
        )
        return

    blocks = ["📊 <b>Статистика оголошень:</b>\n"]
    for item in items:
        latest = await repo.get_latest_stat(item.id)
        previous = await repo.get_previous_stat(item.id)
        blocks.append(format_stat_block(item.title, item.olx_url, latest, previous))

    await message.answer(
        "\n".join(blocks),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
