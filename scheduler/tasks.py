"""
Background scheduler — checks all items every N hours and sends notifications.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database.models import async_session
from database.repository import Repository
from scraper.olx import OLXScraper

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)


def _has_growth(latest_views, latest_fav, latest_ph, prev) -> bool:
    """Return True if any metric increased compared to previous snapshot."""
    if prev is None:
        return False
    return (
        latest_views > prev.views_count
        or latest_fav > prev.favorites_count
        or latest_ph > prev.phone_clicks_count
    )


def _build_notification(item_title: str, item_url: str, latest, prev) -> str:
    def _d(cur: int, old: int) -> str:
        diff = cur - old
        return f" (+{diff})" if diff > 0 else f" ({diff})" if diff < 0 else " (±0)"

    old_v = prev.views_count if prev else 0
    old_f = prev.favorites_count if prev else 0
    old_p = prev.phone_clicks_count if prev else 0

    return (
        f"🔔 <b>Нові дані по оголошенню!</b>\n\n"
        f"📌 <b>{item_title}</b>\n"
        f"🔗 <a href=\"{item_url}\">посилання</a>\n\n"
        f"👁 Перегляди: <code>{latest.views_count}</code>{_d(latest.views_count, old_v)}\n"
        f"⭐ Обране: <code>{latest.favorites_count}</code>{_d(latest.favorites_count, old_f)}\n"
        f"📞 Кліки на телефон: <code>{latest.phone_clicks_count}</code>"
        f"{_d(latest.phone_clicks_count, old_p)}"
    )


async def check_all_items(bot: "Bot") -> None:
    """
    Main scheduled task:
      1. Fetch all items from DB.
      2. Scrape each with a 15-second delay between requests.
      3. Save stats snapshot.
      4. Notify user if any metric grew.
    """
    logger.info("Scheduler: starting check cycle…")

    async with async_session() as session:
        repo = Repository(session)
        items = await repo.get_all_items()

    if not items:
        logger.info("Scheduler: no items to check.")
        return

    async with OLXScraper() as scraper:
        for index, item in enumerate(items):
            if index > 0:
                logger.debug("Scheduler: sleeping %ds before next item…", settings.delay_between_items_sec)
                await asyncio.sleep(settings.delay_between_items_sec)

            logger.info("Scheduler: checking item %d (%s)", item.id, item.title)
            stats_result = await scraper.fetch_stats(item.olx_url)

            if not stats_result.success:
                logger.warning(
                    "Scheduler: failed to scrape item %d — %s", item.id, stats_result.error
                )
                continue

            async with async_session() as session:
                repo = Repository(session)
                previous = await repo.get_latest_stat(item.id)

                new_stat = await repo.save_stat(
                    item_id=item.id,
                    views=stats_result.views,
                    favorites=stats_result.favorites,
                    phone_clicks=stats_result.phone_clicks,
                )
                await session.commit()

            # Notify if growth detected
            grew = _has_growth(
                stats_result.views,
                stats_result.favorites,
                stats_result.phone_clicks,
                previous,
            )
            if grew or previous is None:
                text = _build_notification(
                    item.title, item.olx_url, new_stat, previous
                )
                try:
                    await bot.send_message(
                        chat_id=item.user_id,
                        text=text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception as exc:
                    logger.warning(
                        "Scheduler: failed to notify user %d — %s",
                        item.user_id,
                        exc,
                    )

    logger.info("Scheduler: check cycle complete (%d items).", len(items))


class Scheduler:
    """Wraps APScheduler and exposes simple start/stop."""

    def __init__(self, bot: "Bot") -> None:
        self._bot = bot
        self._scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
        self._scheduler.add_job(
            check_all_items,
            trigger=IntervalTrigger(hours=settings.check_interval_hours),
            args=[bot],
            id="check_items",
            replace_existing=True,
            misfire_grace_time=300,
        )

    def start(self) -> None:
        self._scheduler.start()
        logger.info(
            "Scheduler started — interval=%dh, delay_between=%ds",
            settings.check_interval_hours,
            settings.delay_between_items_sec,
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
