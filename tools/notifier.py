"""Push notification dispatcher supporting Discord Webhooks and local audit log."""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from config import settings, DATA_DIR

logger = logging.getLogger("GamesReviewer.Notifier")


def log_notification_locally(payload: Dict[str, Any]):
    """Logs notification payload locally for audit and debugging."""
    notif_log = DATA_DIR / "notifications.jsonl"
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload
    }
    with open(notif_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_discord_notification(
    title: str,
    description: str,
    game_title: str,
    current_price: float,
    historical_low: float,
    discount_percent: int = 0,
    initial_price: Optional[float] = None,
    store_url: Optional[str] = None,
    review_summary: Optional[str] = None,
    color: int = 0x2ECC71,  # Vibrant Green
    header_image: Optional[str] = None,
    icon_url: Optional[str] = None,
    tags: Optional[list] = None,
    player_modes: Optional[list] = None,
    developers: Optional[list] = None,
    publishers: Optional[list] = None,
    release_date: Optional[str] = None,
    short_description: Optional[str] = None,
) -> bool:
    """Sends a rich embedded notification to a Discord webhook.
    
    Args:
        title: Notification header (e.g. '[Game] - MENOR PREÇO HISTÓRICO').
        description: Short introductory description.
        game_title: Name of the game.
        current_price: Current price in BRL.
        historical_low: Lowest price in BRL history.
        discount_percent: Percentage discount.
        initial_price: Regular full price without promotion in BRL.
        store_url: Steam Store URL.
        review_summary: Formatted reviews (e.g. '96% de aprovação (3.420 análises)').
        color: Discord embed hex color code.
        header_image: Official Steam header banner URL.
        icon_url: Official Steam game icon or capsule URL.
        tags: List of top community tags.
        player_modes: Player count modalities (singleplayer, coop, online, etc.).
        developers: List of game developers.
        publishers: List of game publishers.
        release_date: Official release date string.
        short_description: Steam official short description.
        
    Returns:
        True if sent successfully, False otherwise.
    """
    fields = []

    # Compute regular non-promotional price if not provided
    regular_price = initial_price
    if (regular_price is None or regular_price <= current_price) and discount_percent > 0 and current_price > 0:
        regular_price = round(current_price / (1.0 - (discount_percent / 100.0)), 2)

    if regular_price and regular_price > current_price:
        fields.append({"name": "💰 Preço sem Promoção", "value": f"~~R$ {regular_price:.2f}~~", "inline": True})
        fields.append({"name": "💵 Preço Atual", "value": f"**R$ {current_price:.2f}**", "inline": True})
    else:
        fields.append({"name": "💵 Preço Atual", "value": f"**R$ {current_price:.2f}**", "inline": True})

    if discount_percent > 0:
        fields.append({"name": "🔥 Desconto", "value": f"**-{discount_percent}%**", "inline": True})

    fields.append({"name": "📉 Menor Histórico", "value": f"**R$ {historical_low:.2f}**", "inline": True})
    
    if review_summary:
        fields.append({"name": "⭐ Avaliações na Steam", "value": review_summary, "inline": True})

    if release_date:
        fields.append({"name": "📅 Lançamento", "value": release_date, "inline": True})

    if player_modes:
        fields.append({"name": "👥 Modos de Jogo", "value": ", ".join(player_modes), "inline": True})

    if developers:
        fields.append({"name": "🛠️ Desenvolvedor", "value": ", ".join(developers), "inline": True})

    if publishers:
        fields.append({"name": "🏢 Distribuidora", "value": ", ".join(publishers), "inline": True})

    if tags:
        fields.append({"name": "🏷️ Tags", "value": ", ".join(tags[:6]), "inline": False})
        
    if store_url:
        fields.append({"name": "🛒 Acessar na Steam", "value": f"[Ver na Loja Steam]({store_url})", "inline": False})

    if short_description:
        fields.append({"name": "📝 Sobre o Jogo", "value": f"-# {short_description}", "inline": False})

    embed: Dict[str, Any] = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {
            "text": f"Steam Assistant • Menor Preço Histórico (BRL) • {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        }
    }

    if store_url:
        embed["url"] = store_url

    if icon_url:
        embed["thumbnail"] = {"url": icon_url}

    if header_image:
        embed["image"] = {"url": header_image}

    payload = {
        "username": "Games Reviewer AI",
        "avatar_url": "https://upload.wikimedia.org/wikipedia/commons/8/83/Steam_icon_logo.svg",
        "embeds": [embed]
    }

    log_notification_locally(payload)

    if not settings.discord_webhook_url:
        logger.warning("DISCORD_WEBHOOK_URL não configurada. Notificação registrada apenas localmente.")
        print(f"\n[LOCAL NOTIFICATION] {title}")
        print(f"Jogo: {game_title} | Preço: R$ {current_price:.2f} (Histórico: R$ {historical_low:.2f})")
        print(f"Resumo: {description}\n")
        return False

    req = urllib.request.Request(
        settings.discord_webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "GamesReviewer-Assistant/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in (200, 204):
                logger.info(f"Notificação Discord enviada com sucesso para: {game_title}")
                import time
                time.sleep(1.2)  # Respeita o rate limit do webhook do Discord
                return True
            logger.error(f"Erro ao enviar para Discord: HTTP {response.status}")
            return False
    except urllib.error.HTTPError as e:
        if e.code == 429:
            import time
            retry_after = float(e.headers.get("Retry-After", 2.0))
            logger.warning(f"Discord rate limit (429). Aguardando {retry_after}s...")
            time.sleep(retry_after + 0.5)
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status in (200, 204)
            except Exception:
                return False
        logger.error(f"Falha HTTP ao enviar para Discord: {e}")
        return False
    except urllib.error.URLError as e:
        logger.error(f"Falha de conexão com webhook do Discord: {e}")
        return False
