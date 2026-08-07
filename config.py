"""
Configuration module.
All settings are read from environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Settings:
    # ── Telegram ────────────────────────────────────────────────────────────
    bot_token: str = field(
        default_factory=lambda: os.getenv(
            "BOT_TOKEN",
            "8810467336:AAGv-TAh9sfJVRvs1DvoN4MipAc_RFNkw5U",
        )
    )

    # ── Database ─────────────────────────────────────────────────────────────
    # Railway injects DATABASE_URL in the form:
    #   postgresql://user:pass@host:port/db
    # SQLAlchemy async driver needs postgresql+asyncpg://...
    database_url: str = field(
        default_factory=lambda: _fix_db_url(
            os.getenv("DATABASE_URL", "postgresql+asyncpg://localhost/olx_tracker")
        )
    )

    # ── Scheduler ────────────────────────────────────────────────────────────
    check_interval_hours: int = int(os.getenv("CHECK_INTERVAL_HOURS", "2"))
    delay_between_items_sec: int = int(os.getenv("DELAY_BETWEEN_ITEMS_SEC", "15"))

    # ── Seed URLs ────────────────────────────────────────────────────────────
    # (title, url) pairs auto-added to DB on first run
    seed_items: List[Tuple[str, str]] = field(
        default_factory=lambda: [
            (
                "Колаген 464г",
                "https://www.olx.ua/d/obyavlenie/premum-collagen-kolagen-morskiy-450g-california-gold-orignal-100-IDZDfTV.html?bs=olx_pro_listing",
            ),
            (
                "Rayban Meta",
                "https://www.olx.ua/d/uk/obyavlenie/okulyari-ray-ban-meta-wayfarergen-2-53mm-shiny-black-transitions-hameleoni-stok-z-ssha-zapakovan-ID10lg5v.html?bs=olx_pro_listing",
            ),
            (
                "Gymshark Mesh",
                "https://www.olx.ua/d/uk/obyavlenie/gymshark-oldskulna-oversayz-futbolka-s-m-l-orignal-100-nova-ID10CriQ.html?bs=olx_pro_listing",
            ),
        ]
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


def _fix_db_url(url: str) -> str:
    """
    Railway / Heroku export DATABASE_URL as 'postgresql://...'
    SQLAlchemy asyncpg driver requires 'postgresql+asyncpg://...'
    """
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://") and "+asyncpg" not in url:
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


settings = Settings()
