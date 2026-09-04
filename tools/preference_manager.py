"""User preference and server configuration manager for Discord Bot.
Manages tags of interest, price thresholds, community wishlists, alert matching,
and active recommendation tracking for auto-cleanup.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import DATA_DIR

logger = logging.getLogger("GamesReviewer.Preferences")

PREFERENCES_FILE = DATA_DIR / "user_preferences.json"
SERVER_CONFIG_FILE = DATA_DIR / "server_config.json"
COMMUNITY_WISHLISTS_FILE = DATA_DIR / "community_wishlists.json"
ACTIVE_ALERTS_FILE = DATA_DIR / "active_alerts.json"

# 12 Official Steam Tags in English with objective descriptions
AVAILABLE_TAGS = {
    "indie": {
        "label": "💎 Indie",
        "description": "Independent and creator-focused productions.",
        "keywords": ["indie"]
    },
    "rpg": {
        "label": "🧙 RPG",
        "description": "Role-playing, character progression, and quests.",
        "keywords": ["rpg", "jrpg", "crpg", "action rpg"]
    },
    "strategy": {
        "label": "🧠 Strategy",
        "description": "Tactical planning, turn-based, grand strategy, and RTS.",
        "keywords": ["strategy", "turn-based strategy", "rts", "grand strategy", "tactical"]
    },
    "puzzle": {
        "label": "🧩 Puzzle",
        "description": "Logic problems, deduction, and environmental puzzles.",
        "keywords": ["puzzle", "logic", "puzzle platformer", "deduction"]
    },
    "pvp": {
        "label": "⚔️ PvP",
        "description": "Competitive multiplayer and player-versus-player modes.",
        "keywords": ["pvp", "competitive", "multiplayer", "online pvp"]
    },
    "horror": {
        "label": "👻 Horror",
        "description": "Psychological horror, survival horror, and tension.",
        "keywords": ["horror", "survival horror", "psychological horror"]
    },
    "action": {
        "label": "💥 Action",
        "description": "Real-time combat, fast-paced mechanics, and shooters.",
        "keywords": ["action", "fps", "shooter", "hack and slash", "beat 'em up"]
    },
    "adventure": {
        "label": "🗺️ Adventure",
        "description": "Exploration, narrative journeys, and story-rich quests.",
        "keywords": ["adventure", "story rich", "exploration", "point & click"]
    },
    "survival": {
        "label": "🏕️ Survival",
        "description": "Resource gathering, crafting, and hazard survival.",
        "keywords": ["survival", "survival crafting", "open world survival craft"]
    },
    "roguelike": {
        "label": "🔄 Roguelike/lite",
        "description": "Procedural generation, permadeath, and run-based progression.",
        "keywords": ["roguelike", "roguelite", "action roguelike", "traditional roguelike", "rogue-lite", "rogue-like"]
    },
    "management": {
        "label": "📊 Management",
        "description": "Base building, resource management, and economy simulation.",
        "keywords": ["management", "resource management", "base building", "city builder", "economy", "simulation"]
    },
    "tower_defense": {
        "label": "🏰 Tower Defense",
        "description": "Grid strategy, wave defense, and tactical tower placement.",
        "keywords": ["tower defense"]
    }
}

PRICE_TIERS = [
    {"label": "🟢 Até R$ 10,00", "value": 10.0},
    {"label": "🟡 Até R$ 20,00", "value": 20.0},
    {"label": "🟠 Até R$ 50,00", "value": 50.0},
    {"label": "🔴 Até R$ 100,00", "value": 100.0},
    {"label": "♾️ Qualquer Preço (Sem Limite)", "value": 999999.0}
]

TAG_EMOJI_MAP = {
    "💎": "indie",
    "🧙": "rpg",
    "🧠": "strategy",
    "🧩": "puzzle",
    "⚔️": "pvp",
    "👻": "horror",
    "💥": "action",
    "🗺️": "adventure",
    "🏕️": "survival",
    "🔄": "roguelike",
    "📊": "management",
    "🏰": "tower_defense"
}

PRICE_EMOJI_MAP = {
    "🟢": 10.0,
    "🟡": 20.0,
    "🟠": 50.0,
    "🔴": 100.0,
    "♾️": 999999.0
}


class PreferenceManager:
    """Handles JSON storage for user tags, price caps, and server settings."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self):
        for path, default in [
            (PREFERENCES_FILE, {}),
            (SERVER_CONFIG_FILE, {}),
            (COMMUNITY_WISHLISTS_FILE, {}),
            (ACTIVE_ALERTS_FILE, [])
        ]:
            if not path.exists():
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2)

    def _read_json(self, path: Path) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {} if path != ACTIVE_ALERTS_FILE else []

    def _write_json(self, path: Path, data: Any):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --- User Preferences ---

    def get_user_preference(self, user_id: int) -> Dict[str, Any]:
        prefs = self._read_json(PREFERENCES_FILE)
        return prefs.get(str(user_id), {
            "tags": [],
            "max_price": 999999.0,
            "steam_id": None
        })

    def update_user_tags(self, user_id: int, tags: List[str]):
        prefs = self._read_json(PREFERENCES_FILE)
        user_key = str(user_id)
        if user_key not in prefs:
            prefs[user_key] = {"tags": [], "max_price": 999999.0, "steam_id": None}
        prefs[user_key]["tags"] = tags
        self._write_json(PREFERENCES_FILE, prefs)

    def add_user_tag(self, user_id: int, tag: str) -> List[str]:
        prefs = self._read_json(PREFERENCES_FILE)
        user_key = str(user_id)
        if user_key not in prefs:
            prefs[user_key] = {"tags": [], "max_price": 999999.0, "steam_id": None}
        current_tags = prefs[user_key].get("tags", [])
        if tag not in current_tags:
            current_tags.append(tag)
            prefs[user_key]["tags"] = current_tags
            self._write_json(PREFERENCES_FILE, prefs)
        return current_tags

    def remove_user_tag(self, user_id: int, tag: str) -> List[str]:
        prefs = self._read_json(PREFERENCES_FILE)
        user_key = str(user_id)
        if user_key in prefs:
            current_tags = prefs[user_key].get("tags", [])
            if tag in current_tags:
                current_tags.remove(tag)
                prefs[user_key]["tags"] = current_tags
                self._write_json(PREFERENCES_FILE, prefs)
                return current_tags
        return []

    def update_user_max_price(self, user_id: int, max_price: float):
        prefs = self._read_json(PREFERENCES_FILE)
        user_key = str(user_id)
        if user_key not in prefs:
            prefs[user_key] = {"tags": [], "max_price": 999999.0, "steam_id": None}
        prefs[user_key]["max_price"] = max_price
        self._write_json(PREFERENCES_FILE, prefs)

    def set_user_steam_id(self, user_id: int, steam_id: str):
        prefs = self._read_json(PREFERENCES_FILE)
        user_key = str(user_id)
        if user_key not in prefs:
            prefs[user_key] = {"tags": [], "max_price": 999999.0, "steam_id": None}
        prefs[user_key]["steam_id"] = steam_id
        self._write_json(PREFERENCES_FILE, prefs)

        comm = self._read_json(COMMUNITY_WISHLISTS_FILE)
        comm[str(user_id)] = steam_id
        self._write_json(COMMUNITY_WISHLISTS_FILE, comm)

    def get_all_community_steam_ids(self) -> List[str]:
        comm = self._read_json(COMMUNITY_WISHLISTS_FILE)
        return list(set(comm.values()))

    # --- Server Configuration ---

    def set_announcement_channel(self, guild_id: int, channel_id: int):
        config = self._read_json(SERVER_CONFIG_FILE)
        if str(guild_id) not in config:
            config[str(guild_id)] = {}
        config[str(guild_id)]["announcement_channel_id"] = channel_id
        self._write_json(SERVER_CONFIG_FILE, config)

    def get_announcement_channel(self, guild_id: int) -> Optional[int]:
        config = self._read_json(SERVER_CONFIG_FILE)
        guild_cfg = config.get(str(guild_id), {})
        return guild_cfg.get("announcement_channel_id")

    def set_panel_messages(self, guild_id: int, category_msg_ids: Any, budget_msg_id: int):
        config = self._read_json(SERVER_CONFIG_FILE)
        if str(guild_id) not in config:
            config[str(guild_id)] = {}
        if isinstance(category_msg_ids, int):
            ids = [category_msg_ids]
        else:
            ids = list(category_msg_ids)
        config[str(guild_id)]["panel_category_message_ids"] = ids
        if ids:
            config[str(guild_id)]["panel_category_message_id"] = ids[0]
        config[str(guild_id)]["panel_budget_message_id"] = budget_msg_id
        self._write_json(SERVER_CONFIG_FILE, config)

    def get_panel_messages(self, guild_id: int) -> Dict[str, Any]:
        config = self._read_json(SERVER_CONFIG_FILE)
        guild_cfg = config.get(str(guild_id), {})
        cat_ids = guild_cfg.get("panel_category_message_ids", [])
        if not cat_ids and guild_cfg.get("panel_category_message_id"):
            cat_ids = [guild_cfg.get("panel_category_message_id")]
        return {
            "category_message_ids": cat_ids,
            "category_message_id": cat_ids[0] if cat_ids else None,
            "budget_message_id": guild_cfg.get("panel_budget_message_id")
        }

    # --- Active Alerts Tracking & Auto-Cleanup ---

    def save_active_alert(self, alert_data: Dict[str, Any]):
        alerts = self._read_json(ACTIVE_ALERTS_FILE)
        if not isinstance(alerts, list):
            alerts = []
        alerts.append(alert_data)
        self._write_json(ACTIVE_ALERTS_FILE, alerts)

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        alerts = self._read_json(ACTIVE_ALERTS_FILE)
        return alerts if isinstance(alerts, list) else []

    def remove_active_alert(self, message_id: int):
        alerts = self._read_json(ACTIVE_ALERTS_FILE)
        if isinstance(alerts, list):
            alerts = [a for a in alerts if a.get("message_id") != message_id]
            self._write_json(ACTIVE_ALERTS_FILE, alerts)

    # --- Matching Algorithm ---

    def find_users_to_notify(self, game_tags: List[str], current_price: float) -> List[int]:
        """Finds all Discord user IDs interested in this game and whose budget allows it."""
        prefs = self._read_json(PREFERENCES_FILE)
        normalized_game_tags = [t.lower() for t in game_tags]
        matching_users = []

        for user_id_str, user_data in prefs.items():
            user_max_price = user_data.get("max_price", 999999.0)
            user_tags = user_data.get("tags", [])

            # 1. Price filter: If game costs more than user's limit, skip
            if current_price > (user_max_price + 0.001):
                continue

            # 2. Tag filter: Check if any of user's subscribed tags match the game's tags
            if not user_tags:
                # If user has no tags selected, notify on any game within budget
                matching_users.append(int(user_id_str))
                continue

            matched = False
            for ut in user_tags:
                tag_def = AVAILABLE_TAGS.get(ut, {})
                keywords = tag_def.get("keywords", [])
                for kw in keywords:
                    if any(kw in gt for gt in normalized_game_tags):
                        matched = True
                        break
                if matched:
                    break

            if matched:
                matching_users.append(int(user_id_str))

        return matching_users


pref_manager = PreferenceManager()
