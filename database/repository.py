"""
Repository — all database CRUD operations.
"""

from __future__ import annotations

import datetime
from typing import List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Item, Stat, User, async_session


class Repository:
    """Async database repository with context-manager support."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── context manager ──────────────────────────────────────────────────────

    @classmethod
    async def create(cls) -> "Repository":
        """Open a new session — caller must call .close() or use async with."""
        session = async_session()
        return cls(session)

    async def close(self) -> None:
        await self._s.close()

    async def __aenter__(self) -> "Repository":
        return self

    async def __aexit__(self, *args) -> None:
        await self._s.commit()
        await self._s.close()

    # ── Users ─────────────────────────────────────────────────────────────────

    async def get_or_create_user(
        self,
        user_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> Tuple[User, bool]:
        """Return (user, created). created=True if inserted."""
        result = await self._s.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            return user, False

        user = User(id=user_id, username=username, first_name=first_name)
        self._s.add(user)
        await self._s.flush()
        return user, True

    async def get_all_user_ids(self) -> List[int]:
        result = await self._s.execute(select(User.id))
        return list(result.scalars().all())

    # ── Items ─────────────────────────────────────────────────────────────────

    async def add_item(
        self,
        user_id: int,
        olx_url: str,
        title: str,
    ) -> Tuple[Item, bool]:
        """Return (item, created). created=False if URL already tracked."""
        result = await self._s.execute(
            select(Item).where(Item.user_id == user_id, Item.olx_url == olx_url)
        )
        item = result.scalar_one_or_none()
        if item is not None:
            return item, False

        item = Item(user_id=user_id, olx_url=olx_url, title=title)
        self._s.add(item)
        await self._s.flush()
        return item, True

    async def get_items_by_user(self, user_id: int) -> List[Item]:
        result = await self._s.execute(
            select(Item).where(Item.user_id == user_id).order_by(Item.created_at)
        )
        return list(result.scalars().all())

    async def get_item_by_id(self, item_id: int) -> Optional[Item]:
        result = await self._s.execute(select(Item).where(Item.id == item_id))
        return result.scalar_one_or_none()

    async def delete_item(self, item_id: int, user_id: int) -> bool:
        result = await self._s.execute(
            delete(Item).where(Item.id == item_id, Item.user_id == user_id)
        )
        return result.rowcount > 0

    async def get_all_items(self) -> List[Item]:
        """Return every item across all users (for scheduler)."""
        result = await self._s.execute(select(Item))
        return list(result.scalars().all())

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def save_stat(
        self,
        item_id: int,
        views: int,
        favorites: int,
        phone_clicks: int,
    ) -> Stat:
        stat = Stat(
            item_id=item_id,
            views_count=views,
            favorites_count=favorites,
            phone_clicks_count=phone_clicks,
        )
        self._s.add(stat)
        await self._s.flush()
        return stat

    async def get_latest_stat(self, item_id: int) -> Optional[Stat]:
        result = await self._s.execute(
            select(Stat)
            .where(Stat.item_id == item_id)
            .order_by(Stat.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_previous_stat(self, item_id: int) -> Optional[Stat]:
        """Second most recent snapshot (for delta calculation)."""
        result = await self._s.execute(
            select(Stat)
            .where(Stat.item_id == item_id)
            .order_by(Stat.timestamp.desc())
            .offset(1)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_stats_history(self, item_id: int, limit: int = 10) -> List[Stat]:
        result = await self._s.execute(
            select(Stat)
            .where(Stat.item_id == item_id)
            .order_by(Stat.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Seed / Upsert (for global seed items) ────────────────────────────────

    async def ensure_seed_item(
        self,
        user_id: int,
        olx_url: str,
        title: str,
    ) -> Item:
        """Idempotent: create item only if not already tracked by this user."""
        item, _ = await self.add_item(user_id=user_id, olx_url=olx_url, title=title)
        return item
