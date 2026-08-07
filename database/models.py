"""
SQLAlchemy async models for OLX Tracker.

Tables:
  users  — registered Telegram users
  items  — OLX listings being tracked per user
  stats  — historical snapshots of listing statistics
"""

from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import settings

# ── Engine & session factory ─────────────────────────────────────────────────

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    """Registered Telegram user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user_id
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    items: Mapped[list[Item]] = relationship("Item", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


class Item(Base):
    """OLX listing being tracked."""

    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("user_id", "olx_url", name="uq_user_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    olx_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="items")
    stats: Mapped[list[Stat]] = relationship(
        "Stat", back_populates="item", cascade="all, delete-orphan",
        order_by="Stat.timestamp.desc()"
    )

    def __repr__(self) -> str:
        return f"<Item id={self.id} title={self.title!r}>"


class Stat(Base):
    """Historical statistics snapshot for an OLX listing."""

    __tablename__ = "stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    views_count: Mapped[int] = mapped_column(Integer, default=0)
    favorites_count: Mapped[int] = mapped_column(Integer, default=0)
    phone_clicks_count: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    item: Mapped[Item] = relationship("Item", back_populates="stats")

    def __repr__(self) -> str:
        return (
            f"<Stat item={self.item_id} views={self.views_count} "
            f"fav={self.favorites_count} ph={self.phone_clicks_count}>"
        )
