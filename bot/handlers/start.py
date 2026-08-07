"""
/start handler — greeting, user registration, and main keyboard.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.keyboards import main_keyboard
from database.repository import Repository

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repository, state: FSMContext) -> None:
    # Always reset FSM state on /start so the user can never get stuck
    await state.clear()

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
        "Просто надішли посилання на оголошення OLX — я сам розпізнаю назву та додам до відстеження. "
        "Перевірятиму статистику кожні 2 години та сповіщатиму про зміни 🔔\n\n"
        "<b>Що вмію:</b>\n"
        "➕ <b>Додати оголошення</b> — додати за посиланням\n"
        "📋 <b>Мої оголошення</b> — список відстежуваних\n"
        "📊 <b>Статистика</b> — перегляди, обране, кліки + динаміка\n"
        "❌ <b>Видалити</b> — прибрати оголошення\n\n"
    )

    if created:
        greeting += "✅ Акаунт зареєстровано. Починаємо!"
    else:
        greeting += "🔄 З поверненням! Відстеження триває."

    await message.answer(
        greeting,
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )
