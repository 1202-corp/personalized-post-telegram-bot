"""
Keyboard builders for inline buttons.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from bot.config import get_settings
from bot.texts import TEXTS, get_texts

settings = get_settings()


def get_start_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Initial onboarding keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("start_btn_start_training", default=TEXTS.get("start_btn_start_training", "🚀 Start Training")), callback_data="start_training")],
        [InlineKeyboardButton(text=t.get("start_btn_how_it_works", default=TEXTS.get("start_btn_how_it_works", "❓ How it works")), callback_data="how_it_works")],
        [
            InlineKeyboardButton(text="🇬🇧 EN", callback_data="set_lang_en"),
            InlineKeyboardButton(text="🇷🇺 RU", callback_data="set_lang_ru"),
        ],
    ])


def get_onboarding_keyboard(lang: str = "en", user_id: int = None, channels: list = None) -> InlineKeyboardMarkup:
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


def get_add_channel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Add channel step keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("add_channel_btn_skip_defaults", default="⏭️ Use defaults"), callback_data="skip_add_channel")],
        [InlineKeyboardButton(text=t.get("add_channel_btn_back", default="⬅️ Back"), callback_data="back_to_onboarding")],
    ])


def get_training_post_keyboard(post_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for rating a training post."""
    t = get_texts(lang)
    buttons = [
        [
            InlineKeyboardButton(text=t.get("training_btn_like", default="👍"), callback_data=f"rate:like:{post_id}"),
            InlineKeyboardButton(text=t.get("training_btn_dislike", default="👎"), callback_data=f"rate:dislike:{post_id}"),
        ],
        [InlineKeyboardButton(text=t.get("training_btn_skip", default="⏭️ Skip"), callback_data=f"rate:skip:{post_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_miniapp_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard with MiniApp button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=t.get("miniapp_btn_open", default="📱 Open MiniApp"),
            web_app=WebAppInfo(url=settings.miniapp_url)
        )],
        [InlineKeyboardButton(text=t.get("miniapp_btn_rate_in_chat", default="💬 Rate in chat"), callback_data="rate_in_chat")],
    ])


def get_training_complete_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard shown after training is complete."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("training_complete_btn_claim_bonus", default="🎁 Claim Bonus Channel"), callback_data="claim_bonus")],
        [InlineKeyboardButton(text=t.get("training_complete_btn_view_feed", default="📰 View My Feed"), callback_data="view_feed")],
    ])


def get_bonus_channel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for adding bonus channel."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("bonus_btn_add", default="➕ Add Bonus Channel"), callback_data="add_bonus_channel")],
        [InlineKeyboardButton(text=t.get("bonus_btn_skip", default="⏭️ Skip"), callback_data="skip_bonus")],
    ])


def get_feed_keyboard(lang: str = "en", has_bonus_channel: bool = False) -> InlineKeyboardMarkup:
    """Main feed menu keyboard. Hides add channel button if user already has bonus channel."""
    t = get_texts(lang)
    buttons = []
    if not has_bonus_channel:
        buttons.append([InlineKeyboardButton(text=t.get("feed_btn_add_channel", default="➕ Add Channel"), callback_data="add_channel_feed")])
    buttons.append([InlineKeyboardButton(text=t.get("feed_btn_settings", default="⚙️ Settings"), callback_data="settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_feed_post_keyboard(post_id: int, lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for a feed post."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t.get("feed_post_btn_like", default="👍"), callback_data=f"feed:like:{post_id}"),
            InlineKeyboardButton(text=t.get("feed_post_btn_dislike", default="👎"), callback_data=f"feed:dislike:{post_id}"),
        ],
    ])


def get_settings_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Settings menu keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_my_channels", default="📋 My Channels"), callback_data="my_channels")],
        [InlineKeyboardButton(text=t.get("settings_btn_retrain", default="🔄 Retrain"), callback_data="retrain")],
        [InlineKeyboardButton(text=t.get("settings_btn_language", default="🌐 Language"), callback_data="change_language")],
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="back_to_feed")],
    ])


def get_confirm_keyboard(action: str, lang: str = "en") -> InlineKeyboardMarkup:
    """Generic confirmation keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t.get("confirm_btn_yes", default="✅ Yes"), callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text=t.get("confirm_btn_no", default="❌ No"), callback_data=f"cancel:{action}"),
        ],
    ])


def get_cancel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Cancel action keyboard."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("cancel_btn_cancel", default="❌ Cancel"), callback_data="cancel")],
    ])


def get_add_channel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for add channel prompt with back button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data="back_to_feed")],
    ])


def get_add_bonus_channel_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for add bonus channel prompt with back button to bonus offer."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Назад"), callback_data="skip_bonus")],
    ])


def get_channels_view_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Keyboard for viewing user's channels with back button."""
    t = get_texts(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t.get("settings_btn_back", default="⬅️ Back"), callback_data="back_to_settings")],
    ])


def get_retrain_keyboard(lang: str = "en", user_id: int = None, channels: list = None) -> InlineKeyboardMarkup:
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
