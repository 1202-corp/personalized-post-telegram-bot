"""Onboarding handlers for training flow."""

import json
import logging
import asyncio

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.context import FSMContext

from bot.core import (
    MessageManager, get_texts, get_settings,
    get_start_keyboard, get_onboarding_keyboard, get_add_channel_keyboard,
    get_bonus_channel_keyboard, get_how_it_works_keyboard,
)
from bot.core.states import TrainingStates
from bot.services import get_core_api, get_user_bot
import html
from .helpers import _get_user_lang, _start_training_session, finish_training_flow

logger = logging.getLogger(__name__)
router = Router()
settings = get_settings()


@router.message(F.web_app_data)
async def on_web_app_data(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext,
):
    """Handle data sent from MiniApp via tg.sendData()."""
    try:
        data = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON from web_app_data: {message.web_app_data.data}")
        return
    
    action = data.get("action")
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    logger.info(f"Received web_app_data from user {user_id}: action={action}")
    
    api = get_core_api()
    await api.update_activity(user_id)
    
    if action == "training_complete":
        rated_count = data.get("rated_count", 0)
        await api.create_log(user_id, "miniapp_training_complete", f"rated_count={rated_count}")
        
        existing_state = await state.get_data()
        is_bonus_training = existing_state.get("is_bonus_training", False)
        is_retrain = existing_state.get("is_retrain", False)
        
        await state.update_data(
            rated_count=rated_count,
            user_id=user_id,
            is_bonus_training=is_bonus_training,
            is_retrain=is_retrain,
        )
        
        await finish_training_flow(chat_id, message_manager, state)
    
    elif action == "interaction":
        post_id = data.get("post_id")
        interaction_type = data.get("type")
        
        if post_id and interaction_type and interaction_type != "skip":
            await api.create_interaction(user_id, post_id, interaction_type)
            await api.create_log(user_id, f"miniapp_post_{interaction_type}", f"post_id={post_id}")
    
    else:
        logger.warning(f"Unknown web_app_data action: {action}")


@router.callback_query(F.data == "start_training")
async def on_start_training(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Handle Start Training button - scrape posts and show MiniApp/chat choice."""
    await message_manager.send_toast(callback)
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    await api.update_activity(user_id)
    await api.create_log(user_id, "start_training_clicked")
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(texts.get("fetching_posts"))
    except Exception:
        pass
    
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]
    
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")
    
    scrape_tasks = []
    for channel in channels_to_scrape[:3]:
        task = user_bot.scrape_channel(channel, limit=settings.posts_per_channel)
        scrape_tasks.append(task)
    
    await asyncio.gather(*scrape_tasks, return_exceptions=True)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang, user_id, channels_to_scrape[:3]),
        )
    except Exception:
        pass


@router.callback_query(F.data == "how_it_works")
async def on_how_it_works(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Show how the bot works."""
    await message_manager.send_toast(callback)
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("how_it_works"),
        reply_markup=get_how_it_works_keyboard(lang),
        tag="menu"
    )


@router.callback_query(F.data == "confirm_training")
async def on_confirm_training(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Start the actual training process."""
    await message_manager.send_toast(callback, "🚀 Starting training...")
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = callback.from_user.id
    
    await api.update_activity(user_id)
    await api.update_user(user_id, status="training")
    await api.create_log(user_id, "training_started")
    
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    await message_manager.send_system(
        callback.message.chat.id,
        texts.get("fetching_posts"),
        tag="menu"
    )
    
    default_channels = settings.default_training_channels.split(",")
    channels_to_scrape = [ch.strip() for ch in default_channels]
    
    user_channels = await api.get_user_channels(user_id)
    for ch in user_channels:
        if ch.get("username"):
            channels_to_scrape.append(f"@{ch['username']}")
    
    scrape_tasks = []
    for channel in channels_to_scrape[:3]:
        task = user_bot.scrape_channel(channel, limit=settings.posts_per_channel)
        scrape_tasks.append(task)
    
    await asyncio.gather(*scrape_tasks, return_exceptions=True)
    
    posts = await api.get_training_posts(
        user_id,
        channels_to_scrape[:3],
        settings.posts_per_channel
    )
    
    if not posts:
        lang = await _get_user_lang(user_id)
        texts = get_texts(lang)
        await message_manager.send_system(
            callback.message.chat.id,
            texts.get("no_posts_training"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
        return
    
    from datetime import datetime
    await state.update_data(
        user_id=user_id,
        training_posts=posts,
        current_post_index=0,
        rated_count=0,
        last_media_ids=[],
        last_activity_ts=datetime.utcnow().timestamp(),
        nudge_stage=0,
    )
    await state.set_state(TrainingStates.rating_posts)
    
    await _start_training_session(callback.message.chat.id, callback.from_user.id, message_manager, state)


@router.callback_query(F.data == "add_channel")
async def on_add_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Prompt user to add a channel."""
    await message_manager.send_toast(callback)
    await state.set_state(TrainingStates.waiting_for_channel)
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("add_channel_prompt"),
            reply_markup=get_add_channel_keyboard(lang),
        )
    except Exception:
        pass


@router.message(TrainingStates.waiting_for_channel)
async def on_channel_input(
    message: Message,
    message_manager: MessageManager,
    state: FSMContext
):
    """Handle channel username input."""
    channel_input = message.text.strip()
    api = get_core_api()
    user_bot = get_user_bot()
    user_id = message.from_user.id
    
    await api.update_activity(user_id)
    lang = await _get_user_lang(user_id)
    texts = get_texts(lang)
    
    # Delete user's message
    await message_manager.delete_user_message(message)
    
    if not channel_input.startswith("@") and not channel_input.startswith("https://t.me/"):
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("invalid_channel_username"),
            auto_delete_after=5.0
        )
        return
    
    if channel_input.startswith("https://t.me/"):
        username = "@" + channel_input.split("/")[-1]
    else:
        username = channel_input
    
    await message_manager.send_temporary(
        message.chat.id,
        texts.get("checking_channel", username=username),
        tag="loading"
    )
    
    join_result = await user_bot.join_channel(username)
    
    if join_result and join_result.get("success"):
        await user_bot.scrape_channel(username, limit=settings.posts_per_channel)
        await api.add_user_channel(user_id, username, is_for_training=True)
        await api.create_log(user_id, "channel_added", username)
        
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("channel_added", username=username),
            auto_delete_after=3.0
        )
        
        await state.clear()
        await message_manager.send_system(
            message.chat.id,
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
            tag="menu"
        )
    else:
        await message_manager.delete_temporary(message.chat.id, tag="loading")
        await message_manager.send_temporary(
            message.chat.id,
            texts.get("cannot_access_channel", username=username),
            auto_delete_after=5.0
        )


@router.callback_query(F.data == "skip_add_channel")
async def on_skip_add_channel(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Skip adding custom channel."""
    await message_manager.send_toast(callback)
    await state.clear()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_start")
async def on_back_to_start(
    callback: CallbackQuery,
    message_manager: MessageManager
):
    """Go back to start menu."""
    await message_manager.send_toast(callback)
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    name = html.escape(callback.from_user.first_name or "there")
    
    try:
        await callback.message.edit_text(
            texts.get("welcome", name=name),
            reply_markup=get_start_keyboard(lang),
        )
    except Exception:
        pass


@router.callback_query(F.data == "back_to_onboarding")
async def on_back_to_onboarding(
    callback: CallbackQuery,
    message_manager: MessageManager,
    state: FSMContext
):
    """Go back to onboarding menu."""
    await message_manager.send_toast(callback)
    await state.clear()
    
    lang = await _get_user_lang(callback.from_user.id)
    texts = get_texts(lang)
    
    try:
        await callback.message.edit_text(
            texts.get("training_intro"),
            reply_markup=get_onboarding_keyboard(lang),
        )
    except Exception:
        pass

