"""
Web scraping of t.me public channel pages (no Telethon, no account).
Uses embed mode (?embed=1&mode=tme) and selectors from Steelio/Telegram-Post-Scraper.
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings

logger = logging.getLogger(__name__)
BASE_URL = "https://t.me"

# Embed mode often returns fuller widget HTML (see Steelio/Telegram-Post-Scraper)
EMBED_SUFFIX = "?embed=1&mode=tme"

# User-Agent that matches Telegram's embed widget requests
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/77.0.3865.90 Safari/537.36 TelegramBot (like TwitterBot)"
)


async def _fetch_html(url: str, use_embed: bool = False) -> Optional[str]:
    """Fetch HTML; use_embed appends ?embed=1&mode=tme for post pages (Steelio style)."""
    settings = get_settings()
    if use_embed:
        url = url.rstrip("/").split("?")[0] + EMBED_SUFFIX
    try:
        async with httpx.AsyncClient(
            timeout=settings.scraper_timeout_sec,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.warning("fetch %s: %s", url, e)
        return None


def _normalize_channel(channel_username: str) -> str:
    """Strip @ and return lowercase username."""
    return (channel_username or "").lstrip("@").strip().lower() or ""


def _parse_date(date_text: str) -> str:
    """Return posted_at string (ISO-like or original)."""
    if not date_text or not date_text.strip():
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return date_text.strip()


def _extract_photo_urls_from_photo_wraps(soup: BeautifulSoup) -> List[str]:
    """Extract image URLs from a.tgme_widget_message_photo_wrap (style background-image:url('...'))."""
    urls: List[str] = []
    for wrap in soup.find_all("a", class_="tgme_widget_message_photo_wrap"):
        style = wrap.get("style") or ""
        match = re.search(r"background-image:url\('([^']+)'\)", style)
        if match:
            urls.append(match.group(1))
    return urls


async def get_post(channel_username: str, post_id: int) -> Optional[Dict[str, Any]]:
    """
    Scrape a single post from t.me/<channel>/<post_id>.
    Uses embed mode and selectors from Steelio/Telegram-Post-Scraper.
    Returns dict with: id, text, date, views, media (image URLs), media_type, first_photo_url, etc.
    """
    channel = _normalize_channel(channel_username)
    if not channel:
        return None
    url = f"{BASE_URL}/{channel}/{post_id}"
    html = await _fetch_html(url, use_embed=True)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    # Text: tgme_widget_message_text (with js-message_text and dir=auto in embed)
    text = ""
    text_elem = soup.find("div", class_="tgme_widget_message_text")
    if not text_elem:
        text_elem = soup.find("div", {"class": re.compile(r"tgme_widget_message_text"), "dir": "auto"})
    if text_elem:
        text = str(text_elem.decode_contents()) if text_elem else ""
        text = text.replace("<br/>", "\n").replace("<br>", "\n").strip()

    # Date: span.tgme_widget_message_meta time.datetime (embed) or a.tgme_widget_message_date
    date_text = ""
    meta = soup.find("span", class_="tgme_widget_message_meta")
    if meta:
        time_elem = meta.find("time", class_="datetime")
        if time_elem:
            date_text = time_elem.get_text(strip=True)
            if not date_text and time_elem.get("datetime"):
                date_text = time_elem["datetime"]
    if not date_text:
        date_elem = soup.find("a", class_="tgme_widget_message_date")
        date_text = date_elem.get_text(strip=True) if date_elem else ""

    # Views
    views_elem = soup.find("span", class_="tgme_widget_message_views")
    views = views_elem.get_text(strip=True) if views_elem else "0"

    # Photos: a.tgme_widget_message_photo_wrap with style background-image:url('...')
    photo_urls = _extract_photo_urls_from_photo_wraps(soup)
    if not photo_urls:
        for img in soup.find_all("img", class_="tgme_widget_message_photo"):
            src = img.get("src")
            if src:
                photo_urls.append(src)

    # Video: div.tgme_widget_message_video_wrap and video[src]
    video_url: Optional[str] = None
    for video_wrap in soup.find_all("div", class_="tgme_widget_message_video_wrap"):
        vid = video_wrap.find("video", src=True)
        if vid and vid.get("src"):
            video_url = vid.get("src")
            break
        a = video_wrap.find("a", href=True)
        if a and a.get("href"):
            video_url = a.get("href")
            break
    if not video_url:
        vid = soup.find("video", src=True)
        if vid:
            video_url = vid.get("src")

    media_type: Optional[str] = None
    first_media_url: Optional[str] = None
    if photo_urls:
        media_type = "photo"
        first_media_url = photo_urls[0]
    elif video_url:
        media_type = "video"
        first_media_url = video_url

    return {
        "id": post_id,
        "channel": channel,
        "text": text,
        "views": views,
        "date": date_text,
        "posted_at": _parse_date(date_text),
        "media": photo_urls,
        "video_url": video_url,
        "media_type": media_type,
        "first_photo_url": photo_urls[0] if photo_urls else None,
        "first_media_url": first_media_url,
        "url": url.split("?")[0],
    }


def _parse_post_ids_from_feed_html(soup: BeautifulSoup, channel: str) -> List[int]:
    """Extract unique post IDs from feed page HTML (links to t.me/channel/123 or t.me/s/channel/123)."""
    ids: List[int] = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        m = re.search(r"(?:/s/)?{}/?(\d+)".format(re.escape(channel)), href)
        if m:
            try:
                pid = int(m.group(1))
                if pid not in ids:
                    ids.append(pid)
            except ValueError:
                pass
    ids.sort(reverse=True)
    return ids


async def get_latest_post_ids_from_feed(
    channel_username: str, limit: int = 10
) -> List[int]:
    """
    Fetch t.me/s/<channel> feed (one page, ~20 posts) and parse post IDs (newest first).
    """
    channel = _normalize_channel(channel_username)
    if not channel:
        return []
    url = f"{BASE_URL}/s/{channel}"
    html = await _fetch_html(url, use_embed=False)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    ids = _parse_post_ids_from_feed_html(soup, channel)
    return ids[:limit]


# Max posts we request from feed. t.me/s/<channel> shows ~20 posts per page (no pagination in HTML).
MAX_FEED_POSTS_PER_PAGE = 200
# When scanning by message_id, stop after this many consecutive 404s (channel start or deleted range).
MAX_CONSECUTIVE_MISSING = 50


async def _get_posts_parallel(
    channel_username: str,
    post_ids: List[int],
    max_concurrent: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch multiple posts in parallel (semaphore-limited). Preserves order by post_id desc.
    """
    if not post_ids:
        return []
    settings = get_settings()
    concurrency = max_concurrent if max_concurrent is not None else settings.scraper_concurrent
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(pid: int) -> Optional[Dict[str, Any]]:
        async with sem:
            return await get_post(channel_username, pid)

    results = await asyncio.gather(*[fetch_one(pid) for pid in post_ids])
    return [p for p in results if p is not None]


async def get_max_message_id_from_feed(channel_username: str) -> Optional[int]:
    """
    Get the highest message_id visible on t.me/s/<channel> (newest post).
    Returns None if feed is empty or unavailable.
    """
    ids = await get_latest_post_ids_from_feed(channel_username, limit=1)
    return ids[0] if ids else None


async def _get_latest_posts_by_scan(
    channel_username: str,
    limit: int,
    start_from_id: int,
    max_consecutive_missing: int = MAX_CONSECUTIVE_MISSING,
) -> List[Dict[str, Any]]:
    """
    Walk message_id from start_from_id down in batches; fetch each batch in parallel.
    Stop when we have `limit` posts or after `max_consecutive_missing` consecutive 404s.
    """
    settings = get_settings()
    batch_size = settings.scraper_concurrent
    posts: List[Dict[str, Any]] = []
    consecutive_missing = 0
    current_id = start_from_id
    while current_id > 0 and len(posts) < limit and consecutive_missing < max_consecutive_missing:
        batch_ids = [current_id - i for i in range(batch_size) if current_id - i > 0]
        if not batch_ids:
            break
        results = await asyncio.gather(
            *[get_post(channel_username, pid) for pid in batch_ids]
        )
        for p in results:
            if p is not None:
                posts.append(p)
        # Consecutive 404s at the end (lowest ids in batch) = trailing Nones
        trailing_nones = 0
        for r in reversed(results):
            if r is None:
                trailing_nones += 1
            else:
                break
        consecutive_missing = consecutive_missing + trailing_nones if trailing_nones == len(results) else trailing_nones
        current_id -= batch_size
    return posts[:limit]


async def get_latest_posts(
    channel_username: str, limit: int = 10, use_feed: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetch the latest N posts. If limit <= 20: one feed page + parallel fetch.
    If limit > 20: scan by message_id (max_id from feed, then get_post for each id).
    """
    channel = _normalize_channel(channel_username)
    if not channel:
        return []
    if use_feed and limit <= 20:
        post_ids = await get_latest_post_ids_from_feed(channel_username, limit)
        if not post_ids:
            post_ids = list(range(1, limit + 1))
        return await _get_posts_parallel(channel_username, post_ids)
    # limit > 20: scan by message_id
    max_id = await get_max_message_id_from_feed(channel_username)
    if max_id is None:
        if not use_feed:
            post_ids = list(range(1, limit + 1))
            return await _get_posts_parallel(channel_username, post_ids)
        return []
    return await _get_latest_posts_by_scan(channel_username, limit, max_id)


async def search_posts(
    channel_username: str,
    query: str,
    limit: int = 20,
    scan_limit: int = MAX_FEED_POSTS_PER_PAGE,
) -> List[Dict[str, Any]]:
    """
    Search posts by text. Fetches up to scan_limit posts (feed if <=20, else scan by message_id),
    filters by query in text. Returns list of matching posts (same shape as get_post), up to `limit`.
    """
    channel = _normalize_channel(channel_username)
    if not channel or not (query or "").strip():
        return []
    q = query.strip().lower()
    # get_latest_posts uses feed for limit<=20, scan by message_id for limit>20
    candidates = await get_latest_posts(channel_username, limit=scan_limit)
    matches: List[Dict[str, Any]] = []
    for post in candidates:
        if len(matches) >= limit:
            break
        if q in (post.get("text") or "").lower():
            matches.append(post)
    return matches


async def get_channel_info(channel_username: str) -> Optional[Dict[str, Any]]:
    """
    Scrape channel page t.me/<channel> for title, description, avatar URL.
    Returns dict with: title, description, avatar_url, username.
    """
    channel = _normalize_channel(channel_username)
    if not channel:
        return None
    url = f"{BASE_URL}/{channel}"
    html = await _fetch_html(url, use_embed=False)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    # Title
    title_elem = soup.find("div", class_="tgme_channel_info_header_title")
    title = title_elem.get_text(strip=True) if title_elem else ""

    # Description
    desc_elem = soup.find("div", class_="tgme_channel_info_description")
    description = desc_elem.get_text(strip=True) if desc_elem else ""

    # Avatar
    avatar_url: Optional[str] = None
    img = soup.find("img", class_="tgme_channel_info_header_image")
    if img and img.get("src"):
        avatar_url = img.get("src")

    return {
        "username": channel,
        "title": title or channel,
        "description": description or None,
        "avatar_url": avatar_url,
    }


async def download_media_url(url: str) -> Optional[bytes]:
    """Download bytes from a URL (e.g. photo from t.me CDN)."""
    try:
        async with httpx.AsyncClient(
            timeout=get_settings().scraper_timeout_sec,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ChannelsScraper/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning("download_media %s: %s", url[:80], e)
        return None
