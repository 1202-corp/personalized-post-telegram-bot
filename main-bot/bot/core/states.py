"""FSM states for bot handlers."""

from aiogram.fsm.state import State, StatesGroup


class TrainingStates(StatesGroup):
    """FSM states for training flow."""
    waiting_for_channel = State()
    rating_posts = State()


class FeedStates(StatesGroup):
    """FSM states for feed operations."""
    adding_bonus_channel = State()
    adding_channel = State()

