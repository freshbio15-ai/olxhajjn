"""
FSM states for the bot.
"""

from aiogram.fsm.state import State, StatesGroup


class AddItem(StatesGroup):
    waiting_for_url = State()    # step 1 — user sends OLX link
    waiting_for_title = State()  # step 2 — user types custom name
