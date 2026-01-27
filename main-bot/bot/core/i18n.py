"""Text resources management for the bot.

Supports multiple languages with per-user language storage.
"""
import json
from pathlib import Path
from typing import Dict, Optional, List
from functools import lru_cache

# Base path for language files
LANGS_DIR = Path(__file__).parent.parent / "lang"

# Will be loaded from config dynamically
SUPPORTED_LANGUAGES = ["en_US", "ru_RU"]  # Default fallback
DEFAULT_LANGUAGE = "en_US"  # Default fallback


def normalize_telegram_language(language_code: Optional[str], supported_languages: List[str], default_language: str) -> str:
    """
    Convert Telegram language_code to locale format.
    
    Args:
        language_code: Telegram language code (e.g., "ru", "en", "ru-RU", "en-US")
        supported_languages: List of supported locales (e.g., ["en_US", "ru_RU"])
        default_language: Default locale if language not supported
    
    Returns:
        Locale string (e.g., "ru_RU", "en_US")
    """
    if not language_code:
        return default_language
    
    # Normalize: remove dashes, convert to lowercase
    lang = language_code.replace("-", "_").lower()
    
    # Direct match (e.g., "ru" -> "ru_RU", "en" -> "en_US")
    if lang == "ru":
        return "ru_RU" if "ru_RU" in supported_languages else default_language
    elif lang == "en":
        return "en_US" if "en_US" in supported_languages else default_language
    
    # Check if already in locale format (e.g., "ru_RU", "en_US")
    if lang in supported_languages:
        return lang
    
    # Extract base language (e.g., "ru_ru" -> "ru", "en_us" -> "en")
    base_lang = lang.split("_")[0] if "_" in lang else lang
    
    # Map base language to locale
    if base_lang == "ru":
        return "ru_RU" if "ru_RU" in supported_languages else default_language
    elif base_lang == "en":
        return "en_US" if "en_US" in supported_languages else default_language
    
    # Unknown language, return default
    return default_language


@lru_cache(maxsize=10)  # Cache up to 10 language files
def _load_language_file(lang: str) -> Dict[str, str]:
    """Load and cache texts for specified language."""
    lang_file = LANGS_DIR / f"{lang}.json"
    
    if not lang_file.exists():
        # Try to get default from config, fallback to hardcoded
        try:
            default = get_default_language()
        except Exception:
            default = DEFAULT_LANGUAGE
        lang_file = LANGS_DIR / f"{default}.json"
    
    with open(lang_file, "r", encoding="utf-8") as f:
        return json.load(f)


class TextManager:
    """
    Per-user text manager with language support.
    
    Usage:
        texts = TextManager(lang="ru_RU")
        message = texts.get("welcome", name="John")
    """
    
    def __init__(self, lang: str = None):
        # Get supported languages and default from config
        supported = get_supported_languages()
        default = get_default_language()
        
        if lang is None:
            lang = default
        
        self.lang = lang if lang in supported else default
        self._texts = _load_language_file(self.lang)
        self._fallback = _load_language_file(default) if self.lang != default else {}
    
    def get(self, key: str, default: Optional[str] = None, **kwargs) -> str:
        """
        Get text by key with optional formatting.
        Falls back to English if key not found in current language.
        """
        text = self._texts.get(key)
        
        if text is None:
            text = self._fallback.get(key, default)
        
        if text is None:
            return f"[{key}]"  # Debug placeholder for missing keys
        
        if kwargs:
            try:
                return text.format(**kwargs)
            except KeyError:
                return text
        
        return text
    
    def __getitem__(self, key: str) -> str:
        """Allow dict-like access: texts['key']"""
        return self.get(key)
    
    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        return key in self._texts or key in self._fallback


def get_texts(lang: Optional[str] = None) -> TextManager:
    """Get TextManager instance for specified language."""
    if lang is None:
        lang = get_default_language()
    return TextManager(lang)


def get_supported_languages() -> List[str]:
    """Get supported languages from config."""
    from bot.core.config import get_settings
    settings = get_settings()
    return settings.supported_languages_list


def get_default_language() -> str:
    """Get default language from config."""
    from bot.core.config import get_settings
    settings = get_settings()
    return settings.default_language


# Legacy compatibility - default English texts
# DEPRECATED: Use get_texts(lang) instead
# Initialize after get_default_language is defined
def _init_legacy_texts() -> Dict[str, str]:
    """Initialize legacy TEXTS dict."""
    return _load_language_file(get_default_language())

TEXTS: Dict[str, str] = {}
# Will be initialized on first import
try:
    TEXTS = _init_legacy_texts()
except Exception:
    # Fallback if config not available
    TEXTS = _load_language_file("en_US")


def set_language(lang: str) -> None:
    """
    DEPRECATED: This function is kept for backwards compatibility.
    Use get_texts(lang) for per-user language support.
    """
    global TEXTS
    supported = get_supported_languages()
    if lang in supported:
        new_texts = _load_language_file(lang)
        TEXTS.clear()
        TEXTS.update(new_texts)
