"""
FSM states for the bot.
"""

from aiogram.fsm.state import State, StatesGroup


class AddItem(StatesGroup):
    waiting_for_url = State()
