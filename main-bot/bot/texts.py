"""Text resources management for the bot.

Supports multiple languages with per-user language storage.
"""
import json
from pathlib import Path
from typing import Dict, Optional
from functools import lru_cache

# Base path for language files
LANGS_DIR = Path(__file__).parent / "langs"

# Supported languages
SUPPORTED_LANGUAGES = ["en", "ru"]
DEFAULT_LANGUAGE = "en"


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _load_language_file(lang: str) -> Dict[str, str]:
    """Load and cache texts for specified language."""
    lang_file = LANGS_DIR / f"{lang}.json"
    
    if not lang_file.exists():
        lang_file = LANGS_DIR / f"{DEFAULT_LANGUAGE}.json"
    
    with open(lang_file, "r", encoding="utf-8") as f:
        return json.load(f)


class TextManager:
    """
    Per-user text manager with language support.
    
    Usage:
        texts = TextManager(lang="ru")
        message = texts.get("welcome", name="John")
    """
    
    def __init__(self, lang: str = DEFAULT_LANGUAGE):
        self.lang = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        self._texts = _load_language_file(self.lang)
        self._fallback = _load_language_file(DEFAULT_LANGUAGE) if self.lang != DEFAULT_LANGUAGE else {}
    
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


def get_texts(lang: str = DEFAULT_LANGUAGE) -> TextManager:
    """Get TextManager instance for specified language."""
    return TextManager(lang)


# Legacy compatibility - default English texts
# DEPRECATED: Use get_texts(lang) instead
TEXTS: Dict[str, str] = _load_language_file(DEFAULT_LANGUAGE)


def set_language(lang: str) -> None:
    """
    DEPRECATED: This function is kept for backwards compatibility.
    Use get_texts(lang) for per-user language support.
    """
    global TEXTS
    if lang in SUPPORTED_LANGUAGES:
        new_texts = _load_language_file(lang)
        TEXTS.clear()
        TEXTS.update(new_texts)
