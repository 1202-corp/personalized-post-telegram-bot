"""
Keyboard builders for inline buttons.
"""

from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from bot.core.config import get_settings
from bot.core.i18n import TEXTS, get_texts, get_supported_languages

settings = get_settings()

# Language flags mapping
LANGUAGE_FLAGS = {
    "en_US": "🇺🇸",
    "ru_RU": "🇷🇺",
}


def get_next_language(current_lang: str) -> str:
    """Get next language from SUPPORTED_LANGUAGES list (cyclically)."""
    supported = get_supported_languages()
    if not supported:
        return current_lang
    
    try:
        current_index = supported.index(current_lang)
        next_index = (current_index + 1) % len(supported)
        return supported[next_index]
    except ValueError:
        # Current language not in list, return first supported
        return supported[0] if supported else current_lang


def get_language_flag(lang: str) -> str:
    """Get flag emoji for language."""
    return LANGUAGE_FLAGS.get(lang, "🌐")


def get_language_selection_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Language selection keyboard with languages in vertical list with flags."""
    t = get_texts(lang)
    supported = get_supported_languages()
    
    buttons = []
    # Add each language as a separate button in vertical list
    for supported_lang in supported:
        flag = get_language_flag(supported_lang)
        # Get language name from its own language file
        lang_texts = get_texts(supported_lang)
        lang_name = lang_texts.get(f"lang_name_{supported_lang}", supported_lang)
        buttons.append([InlineKeyboardButton(
            text=f"{flag} {lang_name}",
            callback_data=f"select_language:{supported_lang}"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_start_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Initial onboarding keyboard."""
    t = get_texts(lang)
    next_lang = get_next_language(lang)
    current_flag = get_language_flag(lang)
    next_flag = get_language_flag(next_lang)
    
    # Get button text in current language and format with flags
    change_lang_template = t.get("start_btn_change_language", default="{flag1} Change Language {flag2}")
    change_lang_text = change_lang_template.format(flag1=current_flag, flag2=next_flag)
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("start_btn_start_training", default=TEXTS.get("start_btn_start_training", "🚀 Start Training")), callback_data="start_training")],
        [InlineKeyboardButton(text=t.get("start_btn_how_it_works", default=TEXTS.get("start_btn_how_it_works", "❓ How it works")), callback_data="how_it_works")],
        [InlineKeyboardButton(text=change_lang_text, callback_data="cycle_language")],
    ])


def get_onboarding_keyboard(lang: str = "en_US", user_id: int = None, channels: list = None) -> InlineKeyboardMarkup:
    """Onboarding step 2 keyboard - MiniApp as main action."""
    t = get_texts(lang)
    
    # Build MiniApp URL with user context
    miniapp_url = settings.miniapp_url
    if user_id:
        miniapp_url += f"?user_id={user_id}"
        if channels:
            channels_str = ",".join(ch.lstrip("@") for ch in channels)
            miniapp_url += f"&channels={channels_str}"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("onboarding_btn_open_miniapp", default="📱 Обучить в MiniApp"),
            web_app=WebAppInfo(url=miniapp_url)
        )],
        [InlineKeyboardButton(text=t.get("onboarding_btn_rate_in_chat", default="💬 Оценивать в чате"), callback_data="confirm_training")],
        [InlineKeyboardButton(text=t.get("onboarding_btn_back", default="⬅️ Назад"), callback_data="back_to_start")],
    ])


def get_add_channel_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Add channel step keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("add_channel_btn_skip_defaults", default="⏭️ Use defaults"), callback_data="skip_add_channel")],
        [InlineKeyboardButton(text=t.get("add_channel_btn_back", default="⬅️ Back"), callback_data="back_to_onboarding")],
    ])


def get_main_menu_button(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Single row: 'Main menu' button — shown only under the last REGULAR message."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("main_menu_btn", default="📋 Main menu"),
            callback_data="show_main_menu",
        )],
    ])


def append_main_menu_row(
    keyboard: Optional[InlineKeyboardMarkup], lang: str = "en_US"
) -> InlineKeyboardMarkup:
    """Append 'Main menu' row to keyboard. If keyboard is None, return only main menu button."""
    main_row = get_main_menu_button(lang).inline_keyboard[0]
    if keyboard is None or not keyboard.inline_keyboard:
        return InlineKeyboardMarkup(inline_keyboard=[main_row])
    return InlineKeyboardMarkup(
        inline_keyboard=keyboard.inline_keyboard + [main_row]
    )


def get_post_open_in_channel_keyboard(
    post_url: Optional[str], lang: str = "en_US"
) -> Optional[InlineKeyboardMarkup]:
    """Keyboard with only 'Open in channel' button — attach to the post message itself."""
    if not post_url:
        return None
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("post_btn_open_in_channel", default="🔗 Open in channel"),
            url=post_url,
        )],
    ])


def get_training_post_keyboard(post_id: int, lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard for rating a training post (progress + like/skip/dislike). 'Open in channel' is on the post message."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data=f"rate:like:{post_id}"),
            InlineKeyboardButton(text="⏭️", callback_data=f"rate:skip:{post_id}"),
            InlineKeyboardButton(text="👎", callback_data=f"rate:dislike:{post_id}"),
        ],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="◀ Back"), callback_data="back_to_start")],
    ])


def get_miniapp_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard with MiniApp button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("miniapp_btn_open", default="📱 Open MiniApp"),
            web_app=WebAppInfo(url=settings.miniapp_url)
        )],
        [InlineKeyboardButton(text=t.get("miniapp_btn_rate_in_chat", default="💬 Rate in chat"), callback_data="rate_in_chat")],
    ])


def get_training_complete_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard shown after training is complete. No 'My Feed' - posts are pushed only."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("training_complete_btn_claim_bonus", default="🎁 Claim Bonus Channel"), callback_data="claim_bonus")],
        [InlineKeyboardButton(text=t.get("settings_btn_my_channels", default="📋 My Channels"), callback_data="my_channels")],
    ])


def get_bonus_channel_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard for adding bonus channel."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("bonus_btn_add", default="➕ Add Bonus Channel"), callback_data="add_bonus_channel")],
        [InlineKeyboardButton(text=t.get("bonus_btn_skip", default="⏭️ Skip"), callback_data="skip_bonus")],
    ])


def get_feed_keyboard(
    lang: str = "en_US",
    has_bonus_channel: bool = False,
    mailing_any_on: bool = False,
) -> InlineKeyboardMarkup:
    """Main feed menu keyboard. mailing_any_on: True = show 'Turn off mailing' (🔔), False = show 'Turn on mailing' (🔕)."""
    t = get_texts(lang)
    buttons = [
        [InlineKeyboardButton(text=t.get("feed_btn_add_channel", default="➕ Add Channel"), callback_data="add_channel_feed")],
        [InlineKeyboardButton(text=t.get("settings_btn_my_channels", default="📋 My Channels"), callback_data="my_channels")],
    ]
    if mailing_any_on:
        buttons.append([InlineKeyboardButton(
            text=t.get("feed_btn_turn_off_mailing", default="🔔 Turn off mailing"),
            callback_data="mailing_toggle_all",
        )])
    else:
        buttons.append([InlineKeyboardButton(
            text=t.get("feed_btn_turn_on_mailing", default="🔕 Turn on mailing"),
            callback_data="mailing_toggle_all",
        )])
    buttons.append([InlineKeyboardButton(text=t.get("feed_btn_settings", default="⚙️ Settings"), callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_feed_post_keyboard(
    post_id: int,
    lang: str = "en_US",
    post_message_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Keyboard for 'How do you like this post?' message (like/skip/dislike).
    'Open in channel' is attached to the post message itself, not here.
    If post_message_id is set, it is stored in callback_data so the reaction is set on the exact post message.
    """
    t = get_texts(lang)
    suffix = f":{post_message_id}" if post_message_id is not None else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t.get("feed_post_btn_like", default="👍"), callback_data=f"feed:like:{post_id}{suffix}"),
            InlineKeyboardButton(text=t.get("feed_post_btn_skip", default="⏭"), callback_data=f"feed:skip:{post_id}{suffix}"),
            InlineKeyboardButton(text=t.get("feed_post_btn_dislike", default="👎"), callback_data=f"feed:dislike:{post_id}{suffix}"),
        ],
    ])


def get_settings_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Settings menu keyboard. Retrain is per-channel only (removed from here)."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_language", default="🌐 Language"), callback_data="change_language")],
        [InlineKeyboardButton(text=t.get("settings_btn_delete_account", default="🗑️ Delete account"), callback_data="delete_account")],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="back_to_feed")],
    ])


def get_confirm_keyboard(action: str, lang: str = "en_US") -> InlineKeyboardMarkup:
    """Generic confirmation keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t.get("confirm_btn_yes", default="✅ Yes"), callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text=t.get("confirm_btn_no", default="❌ No"), callback_data=f"cancel:{action}"),
        ],
    ])


def get_cancel_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Cancel action keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("cancel_btn_cancel", default="❌ Cancel"), callback_data="cancel")],
    ])


def get_add_channel_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard for add channel prompt with back button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data="back_to_feed")],
    ])


def get_add_bonus_channel_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard for add bonus channel prompt with back button to bonus offer."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data="skip_bonus")],
    ])


def get_channels_view_keyboard(lang: str = "en_US", has_bonus_channel: bool = False) -> InlineKeyboardMarkup:
    """Keyboard for viewing user's channels with add channel and back to feed buttons."""
    t = get_texts(lang)
    buttons = [
        [InlineKeyboardButton(text=t.get("feed_btn_add_channel", default="➕ Add Channel"), callback_data="add_channel_feed")],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="back_to_feed")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_channels_list_keyboard(channels: list, lang: str = "en_US") -> InlineKeyboardMarkup:
    """Add channel first, then one button per channel, then Back."""
    t = get_texts(lang)
    buttons = [
        [InlineKeyboardButton(text=t.get("feed_btn_add_channel", default="➕ Add Channel"), callback_data="add_channel_feed")],
    ]
    for ch in channels:
        channel_id = ch.get("id")
        if channel_id is None:
            continue
        label = (ch.get("title") or "").strip() or ("@" + (ch.get("username") or "").lstrip("@"))
        if not label:
            label = f"Channel {channel_id}"
        buttons.append([InlineKeyboardButton(text=label[:64], callback_data=f"channel_detail:{channel_id}")])
    buttons.append([InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="back_to_feed")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_channel_detail_keyboard(
    channel_id: int,
    mailing_enabled: bool,
    can_delete: bool,
    lang: str = "en_US",
) -> InlineKeyboardMarkup:
    """Channel detail: Toggle mailing, Retrain, Delete (if can_delete), Back."""
    t = get_texts(lang)
    toggle_text = t.get("channel_btn_mailing_off", "🔔 Disable mailing") if mailing_enabled else t.get("channel_btn_mailing_on", "🔕 Enable mailing")
    buttons = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"channel_mailing_toggle:{channel_id}")],
        [InlineKeyboardButton(text=t.get("channel_btn_retrain", default="🎯 Retrain feed"), callback_data="retrain")],
    ]
    if can_delete:
        buttons.append([InlineKeyboardButton(text=t.get("channel_btn_delete", default="🗑️ Remove channel"), callback_data=f"channel_delete:{channel_id}")])
    buttons.append([InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="my_channels")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_retrain_keyboard(lang: str = "en_US", user_id: int = None, channels: list = None) -> InlineKeyboardMarkup:
    """Retrain keyboard with MiniApp and back to settings."""
    t = get_texts(lang)
    
    # Build MiniApp URL with user context
    miniapp_url = settings.miniapp_url
    if user_id:
        miniapp_url += f"?user_id={user_id}"
        if channels:
            channels_str = ",".join(ch.lstrip("@") for ch in channels)
            miniapp_url += f"&channels={channels_str}"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("retrain_btn_miniapp", default="📱 Переобучить в MiniApp"),
            web_app=WebAppInfo(url=miniapp_url)
        )],
        [InlineKeyboardButton(text=t.get("retrain_btn_chat", default="💬 Оценивать в чате"), callback_data="confirm_retrain")],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data="back_to_settings")],
    ])


def get_how_it_works_keyboard(lang: str = "en_US") -> InlineKeyboardMarkup:
    """Keyboard for 'How it works' screen with back button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("onboarding_btn_back", default="⬅️ Назад"), callback_data="back_to_start")],
    ])
