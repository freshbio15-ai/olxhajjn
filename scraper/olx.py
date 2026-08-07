"""
OLX scraper — extracts views, favorites and phone clicks from an OLX listing.

Strategy (in order of preference):
  1. Parse the embedded JSON inside window.__REDUX_STATE__ / window.__INITIAL_STATE__
     which OLX injects into every page as a <script> block.
  2. Fall back to meta-tag / visible-text heuristics.

HTTP client: httpx with real-browser headers + automatic retry on transient errors.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Browser-like headers ──────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.olx.ua/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "cache-control": "max-age=0",
}

# ── Result dataclass ──────────────────────────────────────────────────────────


@dataclass
class OLXStats:
    views: int = 0
    favorites: int = 0
    phone_clicks: int = 0
    title: str = ""
    success: bool = True
    error: str = ""


# ── Scraper class ─────────────────────────────────────────────────────────────


class OLXScraper:
    """Async OLX page scraper."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    async def __aenter__(self) -> "OLXScraper":
        self._client = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=self._timeout,
            follow_redirects=True,
            http2=True,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_stats(self, url: str) -> OLXStats:
        """Fetch and parse statistics for a single OLX listing."""
        assert self._client is not None, "Use async with OLXScraper() as s:"

        try:
            response = await self._client.get(url)
        except httpx.RequestError as exc:
            logger.warning("Network error fetching %s: %s", url, exc)
            return OLXStats(success=False, error=str(exc))

        if response.status_code in (403, 429):
            logger.warning(
                "OLX returned %s for %s — skipping (rate-limited/blocked)",
                response.status_code,
                url,
            )
            return OLXStats(
                success=False,
                error=f"HTTP {response.status_code}",
            )

        if response.status_code != 200:
            logger.warning("Unexpected status %s for %s", response.status_code, url)
            return OLXStats(success=False, error=f"HTTP {response.status_code}")

        html = response.text
        return self._parse(html, url)

    # ── Internal parsers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse(html: str, url: str) -> OLXStats:
        """Try multiple extraction strategies and merge results."""
        stats = OLXStats()

        # ── Strategy 1: window.__REDUX_STATE__ JSON ───────────────────────────
        redux_match = re.search(
            r"window\.__REDUX_STATE__\s*=\s*(\{.+?\});\s*</script>",
            html,
            re.DOTALL,
        )
        if redux_match:
            try:
                data = json.loads(redux_match.group(1))
                _extract_from_redux(data, stats)
                if stats.views or stats.favorites or stats.phone_clicks:
                    logger.debug("Parsed via REDUX_STATE for %s", url)
                    return stats
            except (json.JSONDecodeError, KeyError):
                pass

        # ── Strategy 2: window.__INITIAL_STATE__ JSON ─────────────────────────
        initial_match = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*(?:</script>|window\.)",
            html,
            re.DOTALL,
        )
        if initial_match:
            try:
                data = json.loads(initial_match.group(1))
                _extract_from_initial(data, stats)
                if stats.views or stats.favorites or stats.phone_clicks:
                    logger.debug("Parsed via INITIAL_STATE for %s", url)
                    return stats
            except (json.JSONDecodeError, KeyError):
                pass

        # ── Strategy 3: JSON-LD structured data ──────────────────────────────
        jsonld_matches = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for raw in jsonld_matches:
            try:
                data = json.loads(raw.strip())
                if isinstance(data, dict):
                    _extract_from_jsonld(data, stats)
            except json.JSONDecodeError:
                pass

        # ── Strategy 4: Regex on visible page text ────────────────────────────
        _extract_title_from_html(html, stats)
        _extract_views_from_html(html, stats)
        _extract_favorites_from_html(html, stats)
        _extract_phone_clicks_from_html(html, stats)

        logger.debug(
            "Parsed via fallback heuristics for %s — views=%d fav=%d ph=%d",
            url,
            stats.views,
            stats.favorites,
            stats.phone_clicks,
        )
        return stats


# ── Extraction helpers ────────────────────────────────────────────────────────


def _safe_int(val) -> int:
    try:
        return int(str(val).replace(" ", "").replace("\xa0", "").strip())
    except (TypeError, ValueError):
        return 0


def _extract_from_redux(data: dict, stats: OLXStats) -> None:
    """Navigate known paths in Redux state tree."""
    # Try ad details under different possible keys
    for key in ("adDetails", "ad", "advert"):
        if key in data:
            ad = data[key]
            if isinstance(ad, dict):
                stats.views = _safe_int(ad.get("views", 0))
                stats.favorites = _safe_int(ad.get("saved", ad.get("favorites", 0)))
                stats.phone_clicks = _safe_int(
                    ad.get("phone_clicks", ad.get("phoneClicks", 0))
                )
                stats.title = str(ad.get("title", ad.get("name", "")))
                return

    # Deeper nested: data.advert.ad or data.adView.ad
    for path in [["adView", "ad"], ["advert", "ad"], ["listing", "ad"]]:
        node = data
        for segment in path:
            if isinstance(node, dict) and segment in node:
                node = node[segment]
            else:
                node = None
                break
        if isinstance(node, dict):
            stats.views = _safe_int(node.get("views", 0))
            stats.favorites = _safe_int(
                node.get("saved", node.get("favorites", 0))
            )
            stats.phone_clicks = _safe_int(
                node.get("phone_clicks", node.get("phoneClicks", 0))
            )
            stats.title = str(node.get("title", node.get("name", "")))
            if stats.views or stats.favorites:
                return


def _extract_from_initial(data: dict, stats: OLXStats) -> None:
    _extract_from_redux(data, stats)


def _extract_from_jsonld(data: dict, stats: OLXStats) -> None:
    if data.get("@type") in ("Product", "Offer"):
        stats.title = str(data.get("name", stats.title))


def _extract_title_from_html(html: str, stats: OLXStats) -> None:
    if stats.title:
        return
    m = re.search(r'<h4[^>]+class="[^"]*css-1juynto[^"]*"[^>]*>([^<]+)</h4>', html)
    if not m:
        m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if m:
        stats.title = m.group(1).strip()


def _extract_views_from_html(html: str, stats: OLXStats) -> None:
    if stats.views:
        return
    # OLX renders "123 переглядів" or "123 views" patterns
    patterns = [
        r'"viewCount"\s*:\s*(\d+)',
        r'(\d[\d\s]*)\s*(?:перегляд|перегляди|переглядів|views?)\b',
        r'data-testid="ad-view-count"[^>]*>(\d[\d\s]*)<',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            stats.views = _safe_int(m.group(1))
            if stats.views:
                return


def _extract_favorites_from_html(html: str, stats: OLXStats) -> None:
    if stats.favorites:
        return
    patterns = [
        r'"savedCount"\s*:\s*(\d+)',
        r'"favoriteCount"\s*:\s*(\d+)',
        r'(\d[\d\s]*)\s*(?:обране|збережень|saved|favorites?)\b',
        r'data-testid="favourites-count"[^>]*>(\d[\d\s]*)<',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            stats.favorites = _safe_int(m.group(1))
            if stats.favorites:
                return


def _extract_phone_clicks_from_html(html: str, stats: OLXStats) -> None:
    if stats.phone_clicks:
        return
    patterns = [
        r'"phoneViewCount"\s*:\s*(\d+)',
        r'"phone_views"\s*:\s*(\d+)',
        r'(\d[\d\s]*)\s*(?:кліків|натисн|phone\s*click|phone\s*view)\b',
        r'data-testid="phone-clicks"[^>]*>(\d[\d\s]*)<',
    ]
    for p in patterns:
        m = re.search(p, html, re.IGNORECASE)
        if m:
            stats.phone_clicks = _safe_int(m.group(1))
            if stats.phone_clicks:
                return
