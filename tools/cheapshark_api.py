"""CheapShark API Client for zero-auth historical low price verification."""

import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

from config import DATA_DIR

logger = logging.getLogger("GamesReviewer.CheapShark")

CACHE_FILE = DATA_DIR / "cheapshark_cache.json"


class CheapSharkClient:
    """Client for querying CheapShark game deal & historical low data."""

    BASE_URL = "https://www.cheapshark.com/api/1.0"
    MIN_REQUEST_INTERVAL = 0.35  # Prevent HTTP 429 rate limits

    def __init__(self):
        self._last_request_time = 0.0
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Failed to save CheapShark cache: {e}")

    def _wait_rate_limit(self):
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    def _get_json(self, url: str) -> Optional[Any]:
        self._wait_rate_limit()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "GamesReviewer/1.0 (https://github.com/davisaobf/games-reviewer)",
                "Accept": "application/json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("CheapShark API rate limit reached (HTTP 429).")
            else:
                logger.warning(f"CheapShark HTTP error {e.code} for {url}")
            return None
        except Exception as e:
            logger.debug(f"CheapShark request error: {e}")
            return None

    def get_historical_deal(self, appid: int) -> Optional[Dict[str, Any]]:
        """Fetches historical low discount and price in USD for a given Steam appid."""
        cache_key = str(appid)
        cached = self._cache.get(cache_key)
        now = time.time()

        # Cache for 24 hours
        if cached and (now - cached.get("cached_at", 0)) < 86400:
            return cached.get("data")

        # Step 1: Lookup game ID by steamAppID
        search_url = f"{self.BASE_URL}/games?steamAppID={appid}"
        search_data = self._get_json(search_url)

        if not search_data or not isinstance(search_data, list) or len(search_data) == 0:
            self._cache[cache_key] = {"cached_at": now, "data": None}
            self._save_cache()
            return None

        game_id = search_data[0].get("gameID")
        if not game_id:
            return None

        # Step 2: Fetch game details and historical lowest
        details_url = f"{self.BASE_URL}/games?id={game_id}"
        details = self._get_json(details_url)

        if not details or not isinstance(details, dict):
            return None

        cheapest_ever = details.get("cheapestPriceEver", {})
        deals = details.get("deals", [])

        cheap_usd = float(cheapest_ever.get("price")) if cheapest_ever.get("price") else None
        retail_usd = float(deals[0].get("retailPrice")) if deals and deals[0].get("retailPrice") else None

        if cheap_usd is None or retail_usd is None or retail_usd <= 0:
            result = None
        else:
            max_discount = round((1.0 - (cheap_usd / retail_usd)) * 100)
            result = {
                "game_id": game_id,
                "cheapest_price_usd": cheap_usd,
                "retail_price_usd": retail_usd,
                "max_discount_percent": max_discount,
                "cheapest_date": cheapest_ever.get("date"),
                "title": details.get("info", {}).get("title")
            }

        self._cache[cache_key] = {"cached_at": now, "data": result}
        self._save_cache()
        return result
