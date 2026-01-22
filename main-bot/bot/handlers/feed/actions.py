"""Feed action handlers (bonus channels, settings, channels management)."""

import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts,
    get_feed_keyboard, get_bonus_channel_keyboard,
    get_settings_keyboard, get_add_channel_keyboard,
)
from bot.core.states import FeedStates
from bot.services import get_core_api, get_user_bot
from bot.utils import escape_md
from bot.handlers.training.retrain import start_full_retrain, start_bonus_training

logger = logging.getLogger(__name__)
router = Router()


async def _get_user_lang(user_id: int) -> str:
    """Get user's language preference."""
    api = get_core_api()
    return await api.get_user_language(user_id)


@router.callback_query(F.data == "claim_bonus")
async def on_claim_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show bonus channel claim option."""
    await callback.answer()
    api = get_core_api()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    user_data = await api.get_user(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_ephemeral(
            callback.message.chat.id,
            texts.get("already_have_bonus"),
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("bonus_channel"),
        reply_markup=get_bonus_channel_keyboard(lang),
        tag="menu"
    )


@router.callback_query(F.data == "retrain")
async def on_retrain_model(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Start a new interactive retraining session on user's channels."""
    await callback.answer()

    await start_full_retrain(
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        message_manager=message_manager,
        state=state,
    )


@router.callback_query(F.data == "add_bonus_channel")
async def on_add_bonus_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt for bonus channel."""
    await callback.answer()
    
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    await state.set_state(FeedStates.adding_bonus_channel)
    
    try:
        await callback.message.edit_text(
            texts.get("add_bonus_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang)
        )
    except Exception:
        pass


@router.message(FeedStates.adding_bonus_channel)
async def on_bonus_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle bonus channel input."""
    channel_input = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    elif channel_input.startswith("@"):
        username = channel_input
    else:
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("invalid_channel_username_short"),
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )
    
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=10)
        
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name
        )
        
        add_result = await api.add_user_channel(user_id, username, is_bonus=True)
        if add_result:
            await api.update_user(user_id, bonus_channels_count=1)
            await api.create_log(user_id, "bonus_channel_claimed", username)
        
        await state.clear()
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")

        await start_bonus_training(
            chat_id=message.chat.id,
            user_id=user_id,
            username=username,
            message_manager=message_manager,
            state=state,
        )
    else:
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "skip_bonus")
async def on_skip_bonus(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Skip bonus channel claim."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await callback.answer(texts.get("you_can_claim_later"))
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("feed_ready"),
        reply_markup=get_feed_keyboard(lang, has_bonus_channel=False),
        tag="menu"
    )


@router.callback_query(F.data == "add_channel_feed")
async def on_add_channel_feed(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Add a new channel from feed menu."""
    await callback.answer()
    
    api = get_core_api()
    user_id = callback.from_user.id
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    await state.set_state(FeedStates.adding_channel)
    await message_manager.delete_ephemeral(callback.message.chat.id, tag="bonus_nudge")
    
    try:
        await callback.message.edit_text(
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang)
        )
    except Exception:
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
            tag="menu"
        )


@router.message(FeedStates.adding_channel)
async def on_channel_feed_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle channel input from feed menu - same as bonus channel flow."""
    channel_input = message.text.strip()
    try:
        await message.delete()
    except Exception:
        pass
    
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    user_data = await api.get_user(user_id)
    if user_data and user_data.get("bonus_channels_count", 0) >= 1:
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=True),
            tag="menu"
        )
        return
    
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    elif channel_input.startswith("@"):
        username = channel_input
    else:
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("invalid_channel_username_short"),
            auto_delete_after=5.0
        )
        return
    
    await message_manager.send_ephemeral(
        message.chat.id,
        texts.get("adding_bonus_channel", username=username),
        tag="loading"
    )
    
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=10)
        
        user_obj = message.from_user
        await api.get_or_create_user(
            telegram_id=user_id,
            username=user_obj.username,
            first_name=user_obj.first_name,
            last_name=user_obj.last_name
        )
        
        add_result = await api.add_user_channel(user_id, username, is_bonus=True)
        if add_result:
            await api.update_user(user_id, bonus_channels_count=1)
            await api.create_log(user_id, "bonus_channel_claimed", username)
        
        await state.clear()
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        
        await start_bonus_training(
            chat_id=message.chat.id,
            user_id=user_id,
            username=username,
            message_manager=message_manager,
            state=state,
        )
    else:
        await message_manager.delete_ephemeral(message.chat.id, tag="loading")
        await message_manager.send_ephemeral(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "settings")
async def on_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show settings menu."""
    await callback.answer()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "my_channels")
async def on_my_channels(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show user's channels."""
    await callback.answer()
    api = get_core_api()
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    channels = await api.get_user_channels(callback.from_user.id)
    
    if not channels:
        text = texts.get("no_user_channels")
    else:
        text = texts.get("your_channels_header")
        for ch in channels:
            username = escape_md(ch.get("username", "Unknown"))
            title = escape_md(ch.get("title", ""))
            text += f"• @{username} - {title}\n"
    
    from bot.core import get_channels_view_keyboard
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_channels_view_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_settings")
async def on_back_to_settings(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to settings menu."""
    await callback.answer()
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("settings_title"),
            reply_markup=get_settings_keyboard(lang)
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_feed")
async def on_back_to_feed(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to feed menu."""
    await callback.answer()
    
    api = get_core_api()
    user_data = await api.get_user(callback.from_user.id)
    has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("feed_ready"),
            reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
        )
    except Exception:
        pass


@router.callback_query(F.data == "cancel")
async def on_cancel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Cancel current operation - return to appropriate screen based on user status."""
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await callback.answer(texts.get("cancelled"))
    
    current_state = await state.get_state()
    state_data = await state.get_data()
    
    await state.clear()
    
    api = get_core_api()
    user_data = await api.get_user(callback.from_user.id)
    
    if user_data and user_data.get("is_trained"):
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1
        try:
            await callback.message.edit_text(
                texts.get("feed_ready"),
                reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
            )
        except Exception:
            pass
    elif current_state and "training" in str(current_state).lower():
        from bot.core.keyboards import get_onboarding_keyboard
        try:
            await callback.message.edit_text(
                texts.get("training_intro"),
                reply_markup=get_onboarding_keyboard(lang)
            )
        except Exception:
            pass
    elif current_state and "adding" in str(current_state).lower():
        has_bonus = user_data.get("bonus_channels_count", 0) >= 1 if user_data else False
        if user_data and user_data.get("is_trained"):
            try:
                await callback.message.edit_text(
                    texts.get("feed_ready"),
                    reply_markup=get_feed_keyboard(lang, has_bonus_channel=has_bonus)
                )
            except Exception:
                pass
        else:
            from bot.core.keyboards import get_onboarding_keyboard
            try:
                await callback.message.edit_text(
                    texts.get("training_intro"),
                    reply_markup=get_onboarding_keyboard(lang)
                )
            except Exception:
                pass
    else:
        from bot.core import get_start_keyboard
        name = escape_md(callback.from_user.first_name or "there")
        try:
            await callback.message.edit_text(
                texts.get("welcome", name=name),
                reply_markup=get_start_keyboard(lang)
            )
        except Exception:
            pass

