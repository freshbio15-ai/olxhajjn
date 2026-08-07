"""
Middleware that injects the database Repository into every handler.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database import Repository
from database.models import async_session


class DatabaseMiddleware(BaseMiddleware):
    """Opens a DB session per update, injects Repository into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            from database.repository import Repository as Repo
            repo = Repo(session)
            data["repo"] = repo
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
