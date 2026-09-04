"""Core Antigravity Agent definition and tool registry for Games Reviewer."""

import json
import logging
from pathlib import Path
from typing import Optional

from config import settings
from agent.system_prompt import CORE_SYSTEM_PROMPT
from agent.triggers import price_scan_trigger
from tools.steam_api import SteamClient
from tools.itad_api import evaluate_price_alert
from tools.community_reviews import CommunityReviewAnalyzer
from tools.news_radar import NewsRadar
from tools.notifier import send_discord_notification

logger = logging.getLogger("GamesReviewer.Agent")

# Shared tool instances
steam_client = SteamClient()
review_analyzer = CommunityReviewAnalyzer()
news_radar = NewsRadar()


# ==============================================================================
# Agent Custom Tools (Exposed to the LLM via Antigravity SDK)
# ==============================================================================

def ler_perfil_steam(user_id: str = "") -> str:
    """Lê o perfil público do usuário na Steam, biblioteca de jogos e títulos recentes.
    
    Args:
        user_id: Nome de usuário público ou SteamID (deixe vazio para usar davii123).
        
    Returns:
        JSON string com lista de jogos jogados recentemente e estatísticas.
    """
    uid = user_id.strip() or settings.steam_user_id
    games = SteamClient(user_id=uid).get_owned_games()
    return json.dumps({
        "usuario": uid,
        "total_jogos_identificados": len(games),
        "jogos_recentes": games[:10]
    }, ensure_ascii=False, indent=2)


def buscar_wishlist(user_id: str = "") -> str:
    """Busca a lista de desejos (Wishlist) pública do usuário com preços atuais em Reais (BRL).
    
    Args:
        user_id: Nome de usuário público ou SteamID (deixe vazio para usar davii123).
        
    Returns:
        JSON string com os jogos na wishlist, preços em BRL e percentual de desconto atual.
    """
    uid = user_id.strip() or settings.steam_user_id
    items = SteamClient(user_id=uid).get_wishlist()
    return json.dumps({
        "usuario": uid,
        "quantidade_desejos": len(items),
        "jogos": items
    }, ensure_ascii=False, indent=2)


def verificar_descontos_historicos(
    titulo_jogo: str,
    preco_atual: float,
    desconto_percentual: int,
    appid: int = 0
) -> str:
    """Verifica se uma promoção atinge o menor preço histórico (Lowest Price em BRL) via IsThereAnyDeal.
    
    REGRA ESTRITA: Se preco_atual for maior que o menor preço histórico, encerra silenciosamente.
    
    Args:
        titulo_jogo: Nome exato do jogo.
        preco_atual: Preço atual em Reais (BRL).
        desconto_percentual: Percentual de desconto (ex: 50).
        appid: ID da Steam (opcional).
        
    Returns:
        JSON string com resultado da avaliação e se o alerta deve ser disparado.
    """
    res = evaluate_price_alert(
        game_title=titulo_jogo,
        current_price=preco_atual,
        discount_percent=desconto_percentual,
        appid=appid if appid > 0 else None
    )
    return json.dumps(res, ensure_ascii=False, indent=2)


def buscar_reviews_comunidade(appid: int, titulo_jogo: str = "") -> str:
    """Consulta opiniões reais de jogadores na Steam e no Reddit para avaliar mecânica, desempenho e consenso.
    
    Args:
        appid: ID da Steam do jogo.
        titulo_jogo: Nome do jogo (usado para buscar no Reddit).
        
    Returns:
        JSON string com porcentagem de aprovação, selo oficial e amostras de análises reais.
    """
    title = titulo_jogo or f"AppID {appid}"
    consensus = review_analyzer.summarize_game_consensus(appid, title)
    return json.dumps(consensus, ensure_ascii=False, indent=2)


def consultar_radar_noticias(limite: int = 5) -> str:
    """Verifica as notícias recentes em feeds RSS (r/Games, PC Gamer) filtradas pelo gosto do usuário.
    
    Args:
        limite: Quantidade máxima de manchetes relevantes para retornar.
        
    Returns:
        JSON string com as notícias mais relevantes para o perfil de precisão tática e lógica.
    """
    news = news_radar.get_relevant_news(min_score=2, max_items=limite)
    return json.dumps({
        "total_encontradas": len(news),
        "noticias": news
    }, ensure_ascii=False, indent=2)


def enviar_alerta_discord(
    titulo_jogo: str,
    preco_atual: float,
    menor_historico: float,
    desconto_percent: int,
    justificativa: str = "",
    url_loja: str = "",
    appid: int = 0
) -> str:
    """Envia um alerta push formatado para o canal do Discord do usuário.
    
    Args:
        titulo_jogo: Nome do jogo.
        preco_atual: Preço atual em R$.
        menor_historico: Menor preço histórico em R$.
        desconto_percent: Desconto em %.
        justificativa: Explicação ou resumo adicional.
        url_loja: Link da página do jogo na Steam.
        appid: ID da Steam (opcional, para carregar imagens e detalhes completos).
        
    Returns:
        Status do envio (sucesso ou notificado localmente).
    """
    store_url = url_loja or (f"https://store.steampowered.com/app/{appid}/" if appid else f"https://store.steampowered.com/search/?term={titulo_jogo}")
    details = steam_client.get_game_details(appid) if appid else {}
    
    sent = send_discord_notification(
        title=titulo_jogo,
        description="Oferta disponível na Steam.",
        game_title=titulo_jogo,
        current_price=preco_atual,
        historical_low=menor_historico,
        discount_percent=desconto_percent,
        initial_price=details.get("initial_price") if details else None,
        store_url=store_url,
        review_summary=justificativa if justificativa else None,
        header_image=details.get("header_image") if details else None,
        icon_url=details.get("icon_url") if details else None,
        tags=details.get("genres") if details else None,
        player_modes=details.get("player_modes") if details else None,
        developers=details.get("developers") if details else None,
        publishers=details.get("publishers") if details else None,
        release_date=details.get("release_date") if details else None,
        short_description=details.get("short_description") if details else None,
    )
    return json.dumps({"sucesso": sent, "jogo": titulo_jogo}, ensure_ascii=False)


# List of all tools to expose
AGENT_TOOLS = [
    ler_perfil_steam,
    buscar_wishlist,
    verificar_descontos_historicos,
    buscar_reviews_comunidade,
    consultar_radar_noticias,
    enviar_alerta_discord
]


def build_antigravity_agent(enable_triggers: bool = False):
    """Factory function to build and configure the Google Antigravity Agent."""
    try:
        from google.antigravity import Agent, LocalAgentConfig
    except ImportError:
        logger.error("google-antigravity SDK não encontrado no ambiente.")
        return None

    skills_dir = Path(__file__).resolve().parent.parent / "skills"

    triggers_list = []
    if enable_triggers and price_scan_trigger:
        triggers_list.append(price_scan_trigger)

    config_kwargs = {
        "system_instructions": CORE_SYSTEM_PROMPT,
        "tools": AGENT_TOOLS,
        "skills_paths": [str(skills_dir)] if skills_dir.exists() else None,
        "triggers": triggers_list if triggers_list else None
    }

    if settings.is_gemini_configured:
        config_kwargs["api_key"] = settings.gemini_api_key

    config = LocalAgentConfig(**{k: v for k, v in config_kwargs.items() if v is not None})
    return Agent(config)
