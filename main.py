"""
Entry point for OLX Tracker Bot.

Flow:
  1. Configure logging.
  2. Initialize database (create tables).
  3. Seed default OLX items.
  4. Register bot routers + middleware.
  5. Start scheduler.
  6. Run bot polling.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import items_router, start_router, stats_router
from bot.middlewares import DatabaseMiddleware
from config import settings
from database.models import Base, async_session, engine
from database.repository import Repository
from scheduler.tasks import Scheduler

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── Database initialisation ───────────────────────────────────────────────────

async def init_db() -> None:
    """Create all tables (idempotent)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified.")


# ── Seed items ────────────────────────────────────────────────────────────────

SEED_USER_ID = 0  # virtual "system" user
SEED_USER_NAME = "system_seed"


async def seed_items() -> None:
    """Insert the pre-configured OLX items once (idempotent)."""
    if not settings.seed_items:
        return

    async with async_session() as session:
        repo = Repository(session)
        await repo.get_or_create_user(
            user_id=SEED_USER_ID,
            username=SEED_USER_NAME,
            first_name="System",
        )

        inserted = 0
        for title, url in settings.seed_items:
            _, created = await repo.add_item(
                user_id=SEED_USER_ID,
                olx_url=url,
                title=title,
            )
            if created:
                inserted += 1

        await session.commit()

    if inserted:
        logger.info("Seeded %d new OLX item(s) into DB.", inserted)
    else:
        logger.info("Seed items already present — skipping.")


# ── Bot setup ─────────────────────────────────────────────────────────────────

def build_dispatcher() -> Dispatcher:
    # MemoryStorage keeps FSM state in RAM.
    # For multi-instance deployments swap to RedisStorage.
    dp = Dispatcher(storage=MemoryStorage())

    # Inject repository into every update handler
    dp.update.middleware(DatabaseMiddleware())

    # Register routers in priority order
    dp.include_router(start_router)
    dp.include_router(items_router)
    dp.include_router(stats_router)

    return dp


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info("OLX Tracker Bot starting…")

    await init_db()
    await seed_items()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    scheduler = Scheduler(bot)
    scheduler.start()

    # Kill any existing polling/webhook session before starting.
    # This prevents TelegramConflictError when Render briefly runs
    # two instances during a rolling deploy.
    logger.info("Clearing existing Telegram sessions…")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Starting bot polling…")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        scheduler.stop()
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
