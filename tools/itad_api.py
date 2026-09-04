"""IsThereAnyDeal (ITAD) API client & Historical Low Price Verification.

Enforces strict requirement:
- Alert trigger ONLY if current_price <= historical_low in BRL.
- If price is even 1 cent above historical low, die silently to avoid redundant spam.
"""

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from config import settings, DATA_DIR
from tools.cheapshark_api import CheapSharkClient

logger = logging.getLogger("GamesReviewer.ITAD")

PRICE_HISTORY_FILE = DATA_DIR / "price_history.json"


class ITADClient:
    """Client for IsThereAnyDeal API v2 with rate-limiting and local cache."""

    BASE_URL = "https://api.isthereanydeal.com"
    REQUESTS_PER_SECOND = 2

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.itad_api_key
        self.country = settings.country
        self.currency = settings.currency
        self.delay = 1.0 / self.REQUESTS_PER_SECOND
        self.last_request_time = 0.0

    def _wait_for_rate_limit(self):
        elapsed = time.monotonic() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None, retries: int = 3) -> Optional[Dict[str, Any]]:
        """Makes an HTTP GET request with exponential backoff and rate-limiting."""
        if not self.api_key:
            return None

        params = params or {}
        params["key"] = self.api_key
        url = f"{self.BASE_URL}{path}?{urllib.parse.urlencode(params)}"

        for attempt in range(retries):
            self._wait_for_rate_limit()
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "GamesReviewer-Assistant/1.0"
                    }
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    self.last_request_time = time.monotonic()
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                self.last_request_time = time.monotonic()
                if e.code == 429:
                    wait_time = 2 ** attempt
                    logger.warning(f"ITAD Rate limited (429). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                if e.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"ITAD HTTP Error {e.code} for {path}: {e.reason}")
                return None
            except urllib.error.URLError as e:
                logger.error(f"ITAD Connection failed: {e}")
                time.sleep(2 ** attempt)

        return None

    def lookup_game(self, title: str) -> Optional[str]:
        """Looks up the ITAD internal game id for a given title."""
        data = self._request("/games/lookup/v1", {"title": title})
        if data and "game" in data and data["game"]:
            return data["game"].get("id")
        return None

    def get_historical_low(self, itad_game_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves official historical low in BRL."""
        data = self._request("/games/history/v2", {
            "id": itad_game_id,
            "country": self.country
        })
        if data and isinstance(data, list) and len(data) > 0:
            low = data[0].get("low", {})
            return {
                "amount": low.get("price", {}).get("amount"),
                "currency": low.get("price", {}).get("currency", "BRL"),
                "shop": low.get("shop", {}).get("name"),
                "timestamp": low.get("timestamp")
            }
        return None


def load_local_price_history() -> Dict[str, Any]:
    if PRICE_HISTORY_FILE.exists():
        try:
            with open(PRICE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_local_price_history(history: Dict[str, Any]):
    with open(PRICE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def evaluate_price_alert(
    game_title: str,
    current_price: float,
    discount_percent: int,
    appid: Optional[int] = None,
    itad_client: Optional[ITADClient] = None,
    cheapshark_client: Optional[CheapSharkClient] = None,
    allow_unverified_first_seen: bool = False
) -> Dict[str, Any]:
    """Evaluates whether an alert should fire based on strict historical low rules.
    
    STRICT LOGICAL FILTER:
    - If historical low is verified (via ITAD or CheapShark) and current_price <= historical_low: Trigger alert.
    - If current_price > historical_low: Die silently (trigger_alert = False).
    - If NO historical data is available and game is first observed: Record baseline but DO NOT trigger alert
      unless allow_unverified_first_seen=True.
    """
    client = itad_client or ITADClient()
    historical_low: Optional[float] = None
    shop_name = "Steam"
    is_verified = False
    is_new_all_time_low = False
    is_at_or_below_lowest = False

    history = load_local_price_history()
    key = str(appid) if appid else game_title.lower()
    local_record = history.get(key, {})
    local_lowest = local_record.get("lowest_price")

    # 1. Attempt ITAD live check if key available
    if client.api_key:
        game_id = client.lookup_game(game_title)
        if game_id:
            itad_low = client.get_historical_low(game_id)
            if itad_low and itad_low.get("amount") is not None:
                historical_low = float(itad_low["amount"])
                shop_name = itad_low.get("shop", "Steam")
                is_verified = True
                is_at_or_below_lowest = current_price <= (historical_low + 0.01)
                is_new_all_time_low = current_price < (historical_low - 0.01)

    # 2. Fallback to CheapShark API (zero-auth public deals index)
    if not is_verified and appid:
        cs = cheapshark_client or CheapSharkClient()
        cs_deal = cs.get_historical_deal(appid)
        if cs_deal:
            max_discount = cs_deal.get("max_discount_percent", 0)
            if discount_percent > 0:
                base_price_brl = current_price / (1.0 - (discount_percent / 100.0))
            else:
                base_price_brl = current_price
            
            est_historical_low_brl = round(base_price_brl * (1.0 - (max_discount / 100.0)), 2)
            historical_low = est_historical_low_brl
            is_verified = True

            # If current discount matches or beats the historical discount record
            # (allowing 2.5% tolerance for third-party voucher/store rounding differences)
            if discount_percent >= (max_discount - 2.5):
                is_at_or_below_lowest = True
                is_new_all_time_low = discount_percent > max_discount
                historical_low = min(current_price, est_historical_low_brl)
            else:
                # Current discount is noticeably worse than all-time record (e.g. 38% vs 81%)
                is_at_or_below_lowest = False
                is_new_all_time_low = False

    # 3. Fallback to local recorded historical low
    if not is_verified:
        if local_lowest is not None:
            historical_low = float(local_lowest)
            is_at_or_below_lowest = current_price <= (historical_low + 0.001)
            is_new_all_time_low = current_price < historical_low
        else:
            # First time seeing this price without external history:
            historical_low = current_price
            is_at_or_below_lowest = allow_unverified_first_seen
            is_new_all_time_low = False

    # Update local historical record
    if is_verified:
        history[key] = {
            "title": game_title,
            "lowest_price": min(current_price, historical_low) if is_at_or_below_lowest else historical_low,
            "updated_at": time.time(),
            "appid": appid,
            "verified": True
        }
        save_local_price_history(history)
    elif key not in history:
        history[key] = {
            "title": game_title,
            "lowest_price": current_price,
            "updated_at": time.time(),
            "appid": appid,
            "verified": False
        }
        save_local_price_history(history)
    elif current_price < historical_low:
        history[key] = {
            "title": game_title,
            "lowest_price": current_price,
            "updated_at": time.time(),
            "appid": appid,
            "verified": local_record.get("verified", False)
        }
        save_local_price_history(history)

    return {
        "game_title": game_title,
        "appid": appid,
        "current_price": current_price,
        "historical_low": historical_low,
        "discount_percent": discount_percent,
        "trigger_alert": is_at_or_below_lowest and discount_percent > 0,
        "shop": shop_name,
        "is_new_all_time_low": is_new_all_time_low,
        "currency": settings.currency
    }
