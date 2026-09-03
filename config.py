"""Configuration and environment management for Games Reviewer."""

import os
from pathlib import Path
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    # Load .env from project directory or fallback to ~/.env
    env_local = Path(__file__).resolve().parent / ".env"
    if env_local.exists():
        load_dotenv(dotenv_path=env_local)
    else:
        env_home = Path.home() / ".env"
        if env_home.exists():
            load_dotenv(dotenv_path=env_home)
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    # LLM & SDK
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
    
    # Steam
    steam_api_key: str = os.getenv("STEAM_API_KEY", "").strip()
    steam_user_id: str = os.getenv("STEAM_USER_ID", "davii123").strip()
    
    # IsThereAnyDeal (ITAD)
    itad_api_key: str = os.getenv("ITAD_API_KEY", "").strip()
    
    # Notification & Automation
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    check_interval_seconds: int = int(os.getenv("CHECK_INTERVAL_SECONDS", "259200"))  # Default: 3 days
    
    # Regional Settings
    currency: str = os.getenv("CURRENCY", "BRL").strip()
    country: str = os.getenv("COUNTRY", "BR").strip()

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def is_steam_api_configured(self) -> bool:
        return bool(self.steam_api_key)

    @property
    def is_itad_configured(self) -> bool:
        return bool(self.itad_api_key)

    @property
    def is_discord_configured(self) -> bool:
        return bool(self.discord_webhook_url)

    @property
    def is_discord_bot_configured(self) -> bool:
        return bool(self.discord_bot_token)


settings = Settings()
