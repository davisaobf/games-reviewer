"""Proactive periodic triggers for autonomous background execution.
Monitors wishlist prices against historical lows and scans gaming news every 3 days.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from config import settings, DATA_DIR
from tools.steam_api import SteamClient
from tools.itad_api import evaluate_price_alert
from tools.community_reviews import CommunityReviewAnalyzer
from tools.news_radar import NewsRadar
from tools.notifier import send_discord_notification

logger = logging.getLogger("GamesReviewer.Triggers")

SENT_ALERTS_FILE = DATA_DIR / "sent_alerts.json"


def load_sent_alerts() -> Dict[str, Any]:
    """Loads previously dispatched alerts to prevent duplicate Discord messages."""
    if SENT_ALERTS_FILE.exists():
        try:
            with open(SENT_ALERTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_sent_alerts(alerts: Dict[str, Any]):
    """Persists alert history to ensure single delivery per price point."""
    try:
        with open(SENT_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Erro ao salvar sent_alerts.json: {e}")


try:
    from google.antigravity.triggers import every, TriggerContext
    HAS_ANTIGRAVITY_TRIGGERS = True
except ImportError:
    HAS_ANTIGRAVITY_TRIGGERS = False
    TriggerContext = Any


async def execute_price_and_news_scan(force: bool = False) -> Dict[str, Any]:
    """Scans the wishlist for lowest historical prices and checks RSS news.
    
    Args:
        force: If True, bypasses deduplication and forces sending alerts.
        
    Returns:
        A summary of actions performed.
    """
    logger.info("Iniciando varredura autônoma periódica da Wishlist e Radar de Notícias...")
    steam_client = SteamClient()
    review_analyzer = CommunityReviewAnalyzer()
    news_radar = NewsRadar()

    alerts_triggered = []
    silent_skips = 0
    already_notified_skips = 0

    # Carregar histórico de alertas enviados para deduplicação
    sent_alerts = load_sent_alerts()

    # 1. Varredura da Wishlist
    wishlist = steam_client.get_wishlist()
    logger.info(f"Wishlist carregada com {len(wishlist)} jogos.")

    for item in wishlist:
        current_price = item.get("current_price", 0.0)
        discount = item.get("discount_percent", 0)
        appid = item.get("appid")
        name = item.get("name", "Unknown")

        if discount > 0 and current_price > 0:
            price_eval = evaluate_price_alert(
                game_title=name,
                current_price=current_price,
                discount_percent=discount,
                appid=appid
            )

            if price_eval.get("trigger_alert"):
                app_key = str(appid)
                last_notified = sent_alerts.get(app_key)

                # Regra estrita de deduplicação: se já foi notificado por este preço (ou menor), não repete
                if last_notified and not force:
                    last_price = last_notified.get("price", 0.0)
                    if current_price >= (last_price - 0.001):
                        logger.info(f"Deduplicação: {name} já foi notificado a R$ {last_price:.2f}. Ignorando duplicata.")
                        already_notified_skips += 1
                        continue

                # Menor preço histórico atingido! Obter detalhes da loja e reviews
                game_details = steam_client.get_game_details(appid) or {}
                consensus = review_analyzer.summarize_game_consensus(appid, name)
                
                # Formatar avaliação na Steam: apenas porcentagem e número de reviews
                total_reviews = consensus.get("total_reviews", 0)
                pos_pct = consensus.get("positive_percent", 0)
                if total_reviews > 0:
                    formatted_reviews = f"{pos_pct:.0f}% de aprovação ({total_reviews:,} análises)".replace(",", ".")
                else:
                    formatted_reviews = "Avaliações insuficientes"

                tags = item.get("tags") or game_details.get("genres", [])
                player_modes = game_details.get("player_modes", [])

                sent = send_discord_notification(
                    title=name,
                    description="Oferta disponível na Steam.",
                    game_title=name,
                    current_price=current_price,
                    historical_low=price_eval["historical_low"],
                    discount_percent=discount,
                    initial_price=game_details.get("initial_price"),
                    store_url=f"https://store.steampowered.com/app/{appid}/",
                    review_summary=formatted_reviews,
                    header_image=game_details.get("header_image"),
                    icon_url=game_details.get("icon_url"),
                    tags=tags,
                    player_modes=player_modes,
                    developers=game_details.get("developers"),
                    publishers=game_details.get("publishers"),
                    release_date=game_details.get("release_date") or item.get("release_string"),
                    short_description=game_details.get("short_description"),
                )

                if sent:
                    sent_alerts[app_key] = {
                        "game": name,
                        "price": current_price,
                        "historical_low": price_eval["historical_low"],
                        "discount_percent": discount,
                        "notified_at": datetime.now().isoformat()
                    }
                    save_sent_alerts(sent_alerts)

                alerts_triggered.append({
                    "game": name,
                    "price": current_price,
                    "historical_low": price_eval["historical_low"],
                    "discord_sent": sent
                })
            else:
                silent_skips += 1

    # 2. Varredura do Radar de Notícias
    relevant_news = news_radar.get_relevant_news(min_score=4, max_items=2)
    for news in relevant_news:
        logger.info(f"Notícia altamente relevante identificada: {news['title']}")

    result = {
        "status": "completed",
        "wishlist_scanned": len(wishlist),
        "alerts_triggered": len(alerts_triggered),
        "silent_skips": silent_skips,
        "already_notified_skips": already_notified_skips,
        "details": alerts_triggered,
        "top_news": relevant_news
    }
    logger.info(f"Varredura concluída. Alertas disparados: {len(alerts_triggered)}, Já notificados: {already_notified_skips}, Descartes silenciosos: {silent_skips}")
    return result


async def autonomous_scan_callback(ctx: TriggerContext):
    """Callback function invoked by Google Antigravity SDK triggers."""
    res = await execute_price_and_news_scan()
    if HAS_ANTIGRAVITY_TRIGGERS and hasattr(ctx, "send"):
        msg = f"Varredura autônoma concluída: {res['alerts_triggered']} alertas de menor preço disparados."
        await ctx.send(msg)


# Cria o trigger periódico configurado (3 dias = 259200 segundos)
if HAS_ANTIGRAVITY_TRIGGERS:
    price_scan_trigger = every(settings.check_interval_seconds, autonomous_scan_callback)
else:
    price_scan_trigger = None
