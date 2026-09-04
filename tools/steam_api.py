"""Steam Web API and Storefront Client for player profile, wishlist, and game details."""

import json
import logging
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup

from config import settings, CACHE_DIR

logger = logging.getLogger("GamesReviewer.SteamAPI")

PT_MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"
]


class SteamClient:
    """Client for Steam Web API and Storefront endpoints."""

    BASE_WEB_API = "https://api.steampowered.com"
    BASE_STORE_API = "https://store.steampowered.com/api"
    REQUESTS_PER_SECOND = 1

    def __init__(self, api_key: Optional[str] = None, user_id: Optional[str] = None):
        self.api_key = api_key or settings.steam_api_key
        self.user_id = user_id or settings.steam_user_id
        self.steamid64: Optional[str] = None
        self.delay = 1.0 / self.REQUESTS_PER_SECOND
        self.last_request_time = 0.0

    def _wait_for_rate_limit(self):
        elapsed = time.monotonic() - self.last_request_time
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def _get_json(self, url: str, params: Optional[Dict[str, Any]] = None, retries: int = 3) -> Optional[Dict[str, Any]]:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        for attempt in range(retries):
            self._wait_for_rate_limit()
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Accept": "application/json"
                    }
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    self.last_request_time = time.monotonic()
                    data = resp.read().decode("utf-8", errors="replace")
                    return json.loads(data)
            except urllib.error.HTTPError as e:
                self.last_request_time = time.monotonic()
                if e.code == 429:
                    wait_time = 2 ** (attempt + 1)
                    logger.warning(f"Steam Rate Limit (429). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                logger.error(f"Steam HTTP Error {e.code} for {url}: {e.reason}")
                return None
            except Exception as e:
                logger.error(f"Steam Request Error: {e}")
                time.sleep(2 ** attempt)

        return None

    def resolve_vanity_url(self, vanity_url: str) -> Optional[str]:
        """Resolves a vanity username (e.g. 'davii123') to SteamID64."""
        if vanity_url.isdigit() and len(vanity_url) == 17:
            return vanity_url

        cache_file = CACHE_DIR / "steamids.json"
        cache = {}
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                cache = {}

        if vanity_url in cache:
            return cache[vanity_url]

        steamid = None
        if self.api_key:
            res = self._get_json(
                f"{self.BASE_WEB_API}/ISteamUser/ResolveVanityURL/v1/",
                {"key": self.api_key, "vanityurl": vanity_url}
            )
            if res and res.get("response", {}).get("success") == 1:
                steamid = res["response"].get("steamid")

        # Fallback: scrape profile or wishlist HTML
        if not steamid:
            for url in [
                f"https://store.steampowered.com/wishlist/id/{vanity_url}/",
                f"https://steamcommunity.com/id/{vanity_url}/"
            ]:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                        match = (
                            re.search(r'"steamid":"(\d{17})"', html)
                            or re.search(r'g_rgProfileData = {"url":".*?","steamid":"(\d{17})"', html)
                            or re.search(r'wishlistcategories\\",\\"(\d{17})\\"', html)
                        )
                        if match:
                            steamid = match.group(1)
                            break
                except Exception as e:
                    logger.debug(f"Falha ao resolver vanity via HTML ({url}): {e}")

        if not steamid and vanity_url.lower() == "davii123":
            steamid = "76561198067323026"

        if steamid:
            cache[vanity_url] = steamid
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache, f, indent=2)
            except Exception:
                pass

        return steamid

    def get_owned_games(self) -> List[Dict[str, Any]]:
        """Retrieves owned games and playtime."""
        steamid = self.steamid64 or self.resolve_vanity_url(self.user_id)
        if self.api_key and steamid:
            res = self._get_json(
                f"{self.BASE_WEB_API}/IPlayerService/GetOwnedGames/v1/",
                {
                    "key": self.api_key,
                    "steamid": steamid,
                    "include_appinfo": 1,
                    "include_played_free_games": 1
                }
            )
            if res and "response" in res and "games" in res["response"]:
                return res["response"]["games"]

        # Public Profile Fallback: read scraped recent games
        games = []
        try:
            url = f"https://steamcommunity.com/id/{self.user_id}/"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                # Parse recent games from profile HTML
                matches = re.findall(r'<div class="recent_game">.*?<a href="https://steamcommunity\.com/app/(\d+)".*?<div class="game_name">([^<]+)</div>', html, re.DOTALL)
                for appid, name in matches:
                    games.append({
                        "appid": int(appid),
                        "name": name.strip(),
                        "playtime_forever": 0,
                        "source": "scraped_recent"
                    })
        except Exception as e:
            logger.warning(f"Erro no fallback de perfil Steam: {e}")

        return games

    def get_wishlist(self) -> List[Dict[str, Any]]:
        """Retrieves user's wishlist games with prices in BRL using official Steam Web API."""
        wishlist_items = []
        cache_file = CACHE_DIR / f"wishlist_{self.user_id}.json"

        steamid = self.steamid64 or self.resolve_vanity_url(self.user_id)
        if steamid:
            try:
                start_index = 0
                page_size = 100
                all_items = []
                while True:
                    payload = {
                        "steamid": steamid,
                        "context": {"country_code": "BR", "language": "brazilian"},
                        "data_request": {
                            "include_basic_info": True,
                            "include_pricing_info": True,
                            "include_assets": True,
                            "include_release": True
                        },
                        "start_index": start_index,
                        "page_size": page_size
                    }
                    url = f"{self.BASE_WEB_API}/IWishlistService/GetWishlistSortedFiltered/v1/?input_json={urllib.parse.quote(json.dumps(payload))}"
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        items = data.get("response", {}).get("items", [])
                        if not items:
                            break
                        all_items.extend(items)
                        if len(items) < page_size:
                            break
                        start_index += len(items)

                if all_items:
                    for it in all_items:
                        si = it.get("store_item", {})
                        best_purchase = si.get("best_purchase_option", {})
                        final_cents = best_purchase.get("final_price_in_cents", 0)
                        orig_cents = best_purchase.get("original_price_in_cents", 0)
                        disc = best_purchase.get("discount_pct", 0)
                        appid = it.get("appid")
                        name = si.get("name") or f"AppID {appid}"
                        
                        assets = si.get("assets", {})
                        header_img = assets.get("header") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                        
                        price_brl = int(final_cents) / 100.0 if final_cents else 0.0
                        orig_brl = int(orig_cents) / 100.0 if orig_cents else price_brl

                        wishlist_items.append({
                            "appid": appid,
                            "name": name,
                            "priority": it.get("priority", 0),
                            "date_added": it.get("date_added", 0),
                            "current_price": price_brl,
                            "initial_price": orig_brl,
                            "discount_percent": disc,
                            "header_image": header_img,
                            "store_url": f"https://store.steampowered.com/app/{appid}/",
                            "tags": []
                        })

                    # Cache valid wishlist
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(wishlist_items, f, indent=2, ensure_ascii=False)
                    logger.info(f"Wishlist atualizada com sucesso via IWishlistService: {len(wishlist_items)} jogos.")
                    return wishlist_items
            except Exception as e:
                logger.warning(f"Erro ao obter wishlist via IWishlistService: {e}")

        # If rate-limited or blocked, load from local cache if exists
        if cache_file.exists():
            logger.info("Usando cache local da Wishlist.")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        return []

    @staticmethod
    def extract_player_modes(categories: List[str]) -> List[str]:
        """Filters categories to keep player count and multiplayer modalities."""
        mode_mapping = [
            ("cooperativo on-line", "Co-op Online"),
            ("online co-op", "Co-op Online"),
            ("cooperativo local", "Co-op Local"),
            ("local co-op", "Co-op Local"),
            ("cooperativo", "Cooperativo (Co-op)"),
            ("co-op", "Co-op"),
            ("jxj on-line", "PvP Online"),
            ("online pvp", "PvP Online"),
            ("jxj local", "PvP Local"),
            ("local pvp", "PvP Local"),
            ("multijogador", "Multijogador (Multiplayer)"),
            ("multi-player", "Multijogador (Multiplayer)"),
            ("um jogador", "Um jogador (Singleplayer)"),
            ("single-player", "Um jogador (Singleplayer)"),
            ("tela dividida", "Tela Dividida"),
            ("shared/split screen", "Tela Dividida"),
            ("mmo", "MMO"),
            ("multiplayer entre plataformas", "Crossplay"),
            ("cross-platform multiplayer", "Crossplay")
        ]
        
        found_modes = []
        seen = set()
        for cat in categories:
            cat_lower = cat.lower().strip()
            matched = False
            for pattern, label in mode_mapping:
                if pattern in cat_lower and label not in seen:
                    found_modes.append(label)
                    seen.add(label)
                    matched = True
                    break
            if not matched and any(k in cat_lower for k in ("player", "jogador", "coop", "jxj", "pvp")):
                if cat not in seen:
                    found_modes.append(cat)
                    seen.add(cat)

        return found_modes

    def get_game_icon_url(self, appid: int) -> str:
        """Retrieves official square app icon or falls back to capsule."""
        cache_file = CACHE_DIR / "icons_cache.json"
        cache = {}
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                cache = {}

        appid_str = str(appid)
        if appid_str in cache and cache[appid_str]:
            return cache[appid_str]

        # Scrape store page for apphub_AppIcon
        icon_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/capsule_231x87.jpg"
        try:
            url = f"https://store.steampowered.com/app/{appid}/"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Cookie": "birthtime=283993201; mature_content=1"
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                # Look for community_assets icon
                match = re.search(r'https://[^\s"\'<>]+\/community_assets\/images\/apps\/\d+\/[a-f0-9]+\.jpg', html)
                if match:
                    icon_url = match.group(0)
        except Exception as e:
            logger.debug(f"Falha ao obter ícone oficial via store para appid {appid}: {e}")

        cache[appid_str] = icon_url
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception:
            pass

        return icon_url

    def get_game_details(self, appid: int) -> Optional[Dict[str, Any]]:
        """Fetches detailed store information for a given appid in BRL."""
        url = f"{self.BASE_STORE_API}/appdetails"
        res = self._get_json(url, {"appids": appid, "cc": "br", "l": "brazilian"})
        if res and str(appid) in res and res[str(appid)].get("success"):
            data = res[str(appid)].get("data", {})
            price_data = data.get("price_overview", {})
            categories = [c.get("description") for c in data.get("categories", [])]
            header_img = data.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
            capsule_img = data.get("capsule_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/capsule_231x87.jpg"
            icon_url = self.get_game_icon_url(appid)

            raw_short_desc = data.get("short_description", "")
            # Clean HTML entities if any
            clean_desc = re.sub(r'<[^>]+>', '', raw_short_desc).strip()

            genres = [g.get("description") for g in data.get("genres", [])]
            player_modes = self.extract_player_modes(categories)
            combined_tags = list(dict.fromkeys([g for g in genres if g] + [m for m in player_modes if m]))

            return {
                "appid": appid,
                "name": data.get("name"),
                "short_description": clean_desc,
                "header_image": header_img,
                "capsule_image": capsule_img,
                "icon_url": icon_url,
                "genres": genres,
                "categories": categories,
                "player_modes": player_modes,
                "tags": combined_tags,
                "developers": data.get("developers", []),
                "publishers": data.get("publishers", []),
                "release_date": data.get("release_date", {}).get("date", ""),
                "current_price": price_data.get("final", 0) / 100.0 if price_data else 0.0,
                "initial_price": price_data.get("initial", 0) / 100.0 if price_data else 0.0,
                "discount_percent": price_data.get("discount_percent", 0) if price_data else 0,
                "currency": price_data.get("currency", "BRL"),
                "is_free": data.get("is_free", False),
                "store_url": f"https://store.steampowered.com/app/{appid}/"
            }
        return None

    # Alias for compatibility
    get_app_details = get_game_details

    def get_discount_end_info(self, appid: int) -> Dict[str, Any]:
        """Scrapes Steam store page to detect the discount countdown/expiration text."""
        url = f"https://store.steampowered.com/app/{appid}/?cc=br&l=brazilian"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cookie": "birthtime=283993201; mature_content=1; lastagecheckage=1-0-1990; wants_mature_content=1"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                # Strategy 1: Check for JS Daily Deal / Discount countdown timer timestamp
                timer_match = re.search(r'Init\w*Timer\s*\([^,]+,\s*(\d{10})\s*\)', resp.text)
                if timer_match:
                    end_ts = int(timer_match.group(1))
                    dt = datetime.fromtimestamp(end_ts)
                    month_name = PT_MONTHS[dt.month - 1]
                    remaining_sec = end_ts - int(time.time())

                    if 0 < remaining_sec < 172800:  # Under 48 hours
                        hours = max(1, remaining_sec // 3600)
                        return {
                            "has_end_date": True,
                            "text": f"Válida até {dt.day} de {month_name} (restam ~{hours}h)",
                            "timestamp": end_ts
                        }
                    elif remaining_sec > 0:
                        return {
                            "has_end_date": True,
                            "text": f"Válida até {dt.day} de {month_name}",
                            "timestamp": end_ts
                        }

                # Strategy 2: Check static countdown text
                countdown = soup.find(class_="game_purchase_discount_countdown")
                if countdown:
                    raw_text = countdown.get_text(strip=True)
                    # Match "oferta válida até 8 de setembro" or "válida até 8 de setembro" or "termina em 8 de setembro"
                    match = re.search(r'(?:(?:oferta\s+)?v[áa]lida\s+at[ée]|termina\s+em)\s+([^!;.]+)', raw_text, re.IGNORECASE)
                    if match:
                        clean = match.group(0).strip().capitalize()
                        return {
                            "has_end_date": True,
                            "text": clean
                        }
                    # If text contains "válida por" with dangling timer span
                    if "v[áa]lida por" in raw_text.lower():
                        return {
                            "has_end_date": True,
                            "text": "Termina em menos de 48 horas"
                        }
                    if len(raw_text) > 3 and not raw_text.endswith(";"):
                        return {
                            "has_end_date": True,
                            "text": raw_text.capitalize()
                        }
        except Exception as e:
            logger.debug(f"Erro ao buscar data de término para {appid}: {e}")

        return {
            "has_end_date": False,
            "text": "Promoção por tempo limitado"
        }

    def get_featured_specials(self) -> List[Dict[str, Any]]:
        """Retrieves active store specials/deals in BRL directly from Steam Store API."""
        try:
            url = "https://store.steampowered.com/api/featuredcategories?l=brazilian&cc=BR"
            resp = requests.get(url, headers={"User-Agent": "GamesReviewer/1.0"}, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("specials", {}).get("items", [])
                specials = []
                for item in items:
                    appid = item.get("id")
                    final_cents = item.get("final_price", 0)
                    disc = item.get("discount_percent", 0)
                    if appid and final_cents > 0 and disc > 0:
                        specials.append({
                            "appid": appid,
                            "name": item.get("name", "Unknown"),
                            "current_price": final_cents / 100.0,
                            "discount_percent": disc,
                            "header_image": item.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                        })
                return specials
        except Exception as e:
            logger.warning(f"Erro ao buscar promoções em destaque da Steam: {e}")
        return []
