"""
OLX scraper — extracts views, favorites and phone clicks from an OLX listing.

Strategy order:
  0. OLX internal REST API  (/api/v1/offers/{numeric_id}/)
  1. Recursive search in window.__REDUX_STATE__ JSON
  2. Recursive search in window.__INITIAL_STATE__ JSON
  3. JSON-LD structured data
  4. HTML regex fallbacks
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

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
    "upgrade-insecure-requests": "1",
    "cache-control": "max-age=0",
}

_API_HEADERS = {
    **_HEADERS,
    "Accept": "application/json",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-requested-with": "XMLHttpRequest",
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
        assert self._client is not None, "Use async with OLXScraper() as s:"

        # 1. Fetch the listing HTML page
        try:
            response = await self._client.get(url)
        except httpx.RequestError as exc:
            logger.warning("Network error fetching %s: %s", url, exc)
            return OLXStats(success=False, error=str(exc))

        if response.status_code in (403, 429):
            logger.warning("OLX returned %s for %s — rate limited/blocked", response.status_code, url)
            return OLXStats(success=False, error=f"HTTP {response.status_code}")

        if response.status_code != 200:
            logger.warning("Unexpected status %s for %s", response.status_code, url)
            return OLXStats(success=False, error=f"HTTP {response.status_code}")

        html = response.text

        # 2. Extract numeric offer ID for API call
        numeric_id = _extract_numeric_id(html, url)

        # 3. Try OLX REST API first (most reliable source of truth)
        if numeric_id:
            api_stats = await self._fetch_api(numeric_id)
            if api_stats and (api_stats.views or api_stats.favorites or api_stats.phone_clicks):
                if not api_stats.title:
                    api_stats.title = _extract_title(html)
                logger.info("Got stats via API for offer %s: v=%d f=%d p=%d",
                            numeric_id, api_stats.views, api_stats.favorites, api_stats.phone_clicks)
                return api_stats

        # 4. Fall back to HTML/JSON parsing
        stats = _parse_html(html, url)
        logger.info("Got stats via HTML parse for %s: v=%d f=%d p=%d",
                    url, stats.views, stats.favorites, stats.phone_clicks)
        return stats

    async def _fetch_api(self, offer_id: str) -> Optional[OLXStats]:
        """Call OLX REST API to get offer statistics."""
        assert self._client is not None
        endpoints = [
            f"https://www.olx.ua/api/v1/offers/{offer_id}/",
            f"https://www.olx.ua/api/v2/offers/{offer_id}/",
        ]
        for endpoint in endpoints:
            try:
                resp = await self._client.get(endpoint, headers=_API_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    stats = OLXStats()
                    _search_for_stats(data, stats)
                    if not stats.title:
                        # try title from API response
                        title_val = _deep_get(data, "data", "title") or _deep_get(data, "title")
                        if title_val:
                            stats.title = str(title_val)
                    return stats
                logger.debug("API %s returned %s", endpoint, resp.status_code)
            except Exception as exc:
                logger.debug("API call failed for %s: %s", endpoint, exc)
        return None


# ── Numeric ID extraction ─────────────────────────────────────────────────────


def _extract_numeric_id(html: str, url: str) -> Optional[str]:
    """Extract the numeric OLX offer ID from HTML or URL."""
    # From HTML: "id": 910712416  (7-10 digit number)
    patterns = [
        r'"id"\s*:\s*(\d{7,10})',
        r'data-id=["\'](\d{7,10})["\']',
        r'"offerId"\s*:\s*(\d{7,10})',
        r'"adId"\s*:\s*(\d{7,10})',
        r'offer_id["\s:]+(\d{7,10})',
        r'/offers/(\d{7,10})',
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            return m.group(1)
    return None


# ── Deep dict navigation ──────────────────────────────────────────────────────


def _deep_get(data: Any, *keys: str) -> Any:
    """Navigate nested dicts/lists safely."""
    node = data
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and key.isdigit():
            try:
                node = node[int(key)]
            except IndexError:
                return None
        else:
            return None
    return node


def _safe_int(val: Any) -> int:
    try:
        return int(str(val).replace(" ", "").replace("\xa0", "").strip())
    except (TypeError, ValueError):
        return 0


# ── Recursive statistics search ───────────────────────────────────────────────


def _extract_from_statistics_dict(stats_dict: dict, result: OLXStats) -> bool:
    """Extract views/favorites/phone from a dict that IS the statistics object."""
    views = _safe_int(
        stats_dict.get("views",
        stats_dict.get("viewCount",
        stats_dict.get("view_count", 0)))
    )
    fav = _safe_int(
        stats_dict.get("saved",
        stats_dict.get("favorites",
        stats_dict.get("favoriteCount",
        stats_dict.get("saved_count",
        stats_dict.get("savedCount", 0)))))
    )
    phone = _safe_int(
        stats_dict.get("phone_views",
        stats_dict.get("phone_clicks",
        stats_dict.get("phoneClicks",
        stats_dict.get("phoneViewCount",
        stats_dict.get("phoneViews", 0)))))
    )
    if views or fav or phone:
        result.views = views
        result.favorites = fav
        result.phone_clicks = phone
        return True
    return False


# Keys to skip during recursion (unlikely to contain stats, but large)
_SKIP_KEYS = {"user", "seller", "location", "images", "photos", "map",
              "breadcrumbs", "metadata", "seo", "tracking", "config"}


def _search_for_stats(data: Any, result: OLXStats, depth: int = 0) -> bool:
    """
    Recursively walk the JSON tree to find statistics data.
    Returns True as soon as any non-zero stats are found.
    """
    if depth > 10:
        return False

    if isinstance(data, dict):
        # Priority 1: explicit "statistics" sub-object
        if "statistics" in data and isinstance(data["statistics"], dict):
            if _extract_from_statistics_dict(data["statistics"], result):
                return True

        # Priority 2: direct views key at this level (must be int/positive)
        views_raw = data.get("views", data.get("view_count", data.get("viewCount")))
        if isinstance(views_raw, (int, float)) and int(views_raw) > 0:
            result.views = _safe_int(views_raw)
            result.favorites = _safe_int(
                data.get("saved", data.get("favorites", data.get("saved_count", 0)))
            )
            result.phone_clicks = _safe_int(
                data.get("phone_views", data.get("phone_clicks", data.get("phoneClicks", 0)))
            )
            return True

        # Priority 3: recurse into child dicts/lists
        for key, value in data.items():
            if key in _SKIP_KEYS:
                continue
            if isinstance(value, (dict, list)):
                if _search_for_stats(value, result, depth + 1):
                    return True

    elif isinstance(data, list):
        for item in data[:10]:  # limit list traversal
            if _search_for_stats(item, result, depth + 1):
                return True

    return False


# ── Title extraction ──────────────────────────────────────────────────────────


def _extract_title(html: str) -> str:
    m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        for suffix in (" - OLX.ua", " — OLX.ua", " - OLX", " — OLX"):
            if suffix.lower() in raw.lower():
                raw = raw[: raw.lower().index(suffix.lower())]
        return raw.strip()
    return ""


# ── Main HTML parser ──────────────────────────────────────────────────────────


def _parse_html(html: str, url: str) -> OLXStats:
    stats = OLXStats()

    # Strategy 1 & 2: parse embedded JSON state objects
    for pattern in [
        r"window\.__REDUX_STATE__\s*=\s*(\{.+?\});\s*</script>",
        r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\});\s*(?:</script>|window\.)",
        r"window\.__INITIAL_CONFIG__\s*=\s*(\{.+?\});\s*</script>",
        r'<script id="__NEXT_DATA__"[^>]*>(\{.+?\})</script>',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                _search_for_stats(data, stats)
                if stats.views or stats.favorites or stats.phone_clicks:
                    logger.debug("Found stats in embedded JSON for %s", url)
                    break
            except (json.JSONDecodeError, ValueError):
                pass

    # Strategy 3: JSON-LD
    if not stats.title:
        for raw in re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json.loads(raw.strip())
                if isinstance(data, dict) and data.get("@type") in ("Product", "Offer"):
                    stats.title = str(data.get("name", ""))
            except (json.JSONDecodeError, ValueError):
                pass

    # Strategy 4: HTML regex fallbacks
    if not stats.title:
        stats.title = _extract_title(html)

    if not stats.views:
        for p in [
            # OLX Ukraine exact element: <span data-testid="page-view-counter">Переглядів: 331</span>
            r'data-testid=["\']page-view-counter["\'][^>]*>[^\d]*(\d+)<',
            r'data-testid=["\']page-view-counter["\'][^>]*>Переглядів:\s*(\d+)<',
            r'"viewCount"\s*:\s*(\d+)',
            r'"views"\s*:\s*(\d+)',
            r'(\d+)\s*(?:перегляд|переглядів)',
            r'data-testid="[^"]*view[^"]*"[^>]*>(\d+)',
        ]:
            m2 = re.search(p, html, re.IGNORECASE)
            if m2:
                val = _safe_int(m2.group(1))
                if val:
                    stats.views = val
                    break

    if not stats.favorites:
        for p in [
            r'"savedCount"\s*:\s*(\d+)',
            r'"favoriteCount"\s*:\s*(\d+)',
            r'"saved"\s*:\s*(\d+)',
            r'(\d+)\s*(?:обране|збережень)',
        ]:
            m2 = re.search(p, html, re.IGNORECASE)
            if m2:
                val = _safe_int(m2.group(1))
                if val:
                    stats.favorites = val
                    break

    if not stats.phone_clicks:
        for p in [
            r'"phoneViewCount"\s*:\s*(\d+)',
            r'"phone_views"\s*:\s*(\d+)',
            r'"phoneClicks"\s*:\s*(\d+)',
            r'"phone_clicks"\s*:\s*(\d+)',
        ]:
            m2 = re.search(p, html, re.IGNORECASE)
            if m2:
                val = _safe_int(m2.group(1))
                if val:
                    stats.phone_clicks = val
                    break

    return stats
