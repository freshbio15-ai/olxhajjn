"""
/start handler — greeting + user registration.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from database.repository import Repository

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repository) -> None:
    user = message.from_user
    if user is None:
        return

    _, created = await repo.get_or_create_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    greeting = (
        "👋 Вітаю! Я — <b>OLX Tracker</b>.\n\n"
        "Я автоматично відстежую статистику твоїх оголошень на OLX.ua "
        "і сповіщаю тебе про зміни кожні 2 години.\n\n"
        "<b>Команди:</b>\n"
        "📌 /add &lt;назва&gt; &lt;посилання&gt; — додати оголошення\n"
        "📋 /list — список відстежуваних оголошень\n"
        "📊 /stats — поточна статистика та динаміка\n"
        "🗑 /delete — видалити оголошення\n\n"
    )

    if created:
        greeting += "✅ Твій акаунт зареєстровано. Починаємо відстежувати!"
    else:
        greeting += "🔄 З поверненням! Відстеження продовжується."

    await message.answer(greeting, parse_mode="HTML")
