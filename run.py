"""Main entry point for Games Reviewer (Steam AI Assistant).

Usage:
  python run.py --mode chat          # Interactive conversation with the assistant
  python run.py --mode daemon        # Autonomous background daemon (scans every 3 days)
  python run.py --check-now          # Run an immediate wishlist & price scan
  python run.py --test-discord       # Test Discord webhook integration
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import settings, DATA_DIR
from agent.core_agent import build_antigravity_agent, AGENT_TOOLS
from agent.triggers import execute_price_and_news_scan
from tools.notifier import send_discord_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("GamesReviewer.Main")


async def run_chat_session():
    """Runs an interactive chat session with the Antigravity Agent."""
    if not settings.is_gemini_configured:
        print("\n" + "=" * 60)
        print("⚠️  AVISO: GEMINI_API_KEY não foi detectada no arquivo .env!")
        print("Para conversar com o agente via LLM, configure sua chave com:")
        print('py -3.13 -c "import getpass, pathlib; val = getpass.getpass(\'Enter GEMINI_API_KEY: \'); open(\'.env\', \'a\').write(f\'GEMINI_API_KEY={val}\\n\'); print(\'Saved.\')"')
        print("=" * 60 + "\n")
        return

    agent = build_antigravity_agent(enable_triggers=False)
    if not agent:
        print("Erro ao inicializar o agente Antigravity.")
        return

    print("\n🎮 Bem-vindo ao Games Reviewer (Steam AI Assistant)!")
    print(f"Perfil monitorado: https://steamcommunity.com/id/{settings.steam_user_id}/")
    print("Digite sua pergunta ou 'sair' para encerrar.\n")

    async with agent:
        while True:
            try:
                user_input = input("Você: ").strip()
                if not user_input or user_input.lower() in ("sair", "exit", "quit"):
                    print("Até mais!")
                    break

                response = await agent.chat(user_input)
                print("\nAssistente: ", end="")
                async for chunk in response:
                    print(chunk, end="", flush=True)
                print("\n")
            except (KeyboardInterrupt, EOFError):
                print("\nSessão encerrada.")
                break


DAEMON_PID_FILE = DATA_DIR / "daemon.pid"


def _is_pid_alive(pid: int) -> bool:
    """Checks if a process ID is currently running on Windows."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


async def run_daemon_loop():
    """Runs the autonomous background daemon checking prices and news every 3 days."""
    if DAEMON_PID_FILE.exists():
        try:
            old_pid = int(DAEMON_PID_FILE.read_text(encoding="utf-8").strip())
            if _is_pid_alive(old_pid):
                print(f"\n⚠️  AVISO: Um serviço autônomo já está em execução em segundo plano (PID {old_pid})!")
                print("Para evitar mensagens duplicadas, esta nova instância foi encerrada.\n")
                return
        except Exception:
            pass

    # Record current process PID to enforce single instance
    current_pid = os.getpid()
    try:
        DAEMON_PID_FILE.write_text(str(current_pid), encoding="utf-8")
    except Exception:
        pass

    interval_hours = settings.check_interval_seconds / 3600
    print("\n" + "=" * 60)
    print("🛡️  Games Reviewer - Serviço Autônomo Iniciado")
    print(f"PID: {current_pid}")
    print(f"Perfil Steam: {settings.steam_user_id}")
    print(f"Canal de Notificações: {'Discord Webhook' if settings.is_discord_configured else 'Log Local'}")
    print(f"Intervalo de Verificação: a cada {interval_hours:.1f} horas ({settings.check_interval_seconds}s)")
    print("=" * 60 + "\n")

    try:
        while True:
            try:
                print(f"[{logging.time.strftime('%Y-%m-%d %H:%M:%S')}] Executando ciclo de verificação...")
                result = await execute_price_and_news_scan(force=False)
                print(f"Varredura finalizada. {result['alerts_triggered']} novos alertas disparados ({result.get('already_notified_skips', 0)} já notificados ignorados).")
                print(f"Aguardando próximo ciclo em {interval_hours:.1f} horas...\n")
                await asyncio.sleep(settings.check_interval_seconds)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nServiço autônomo finalizado pelo usuário.")
                break
            except Exception as e:
                logger.error(f"Erro no ciclo autônomo: {e}", exc_info=True)
                await asyncio.sleep(60)
    finally:
        if DAEMON_PID_FILE.exists():
            try:
                DAEMON_PID_FILE.unlink()
            except Exception:
                pass


async def run_check_now(force: bool = False):
    """Executes a single scan cycle immediately and outputs results."""
    print(f"\n🔍 Executando varredura imediata para o perfil: {settings.steam_user_id}...")
    result = await execute_price_and_news_scan(force=force)
    print("\n" + "=" * 50)
    print("📊 RESULTADOS DA VARREDURA:")
    print(f"- Jogos avaliados na Wishlist: {result['wishlist_scanned']}")
    print(f"- Novos Alertas de Menor Preço disparados: {result['alerts_triggered']}")
    print(f"- Promoções já notificadas anteriormente (duplicação prevenida): {result.get('already_notified_skips', 0)}")
    print(f"- Promoções descartadas por estarem acima do menor histórico: {result['silent_skips']}")
    if result['details']:
        print("\nAlertas disparados:")
        for a in result['details']:
            print(f"  • {a['game']}: R$ {a['price']:.2f} (Menor Histórico: R$ {a['historical_low']:.2f}) [Discord: {a['discord_sent']}]")
    if result['top_news']:
        print("\nRadar de Notícias Relevantes:")
        for n in result['top_news']:
            print(f"  • [{n['source']}] {n['title']} (Score: {n['relevance_score']})")
    print("=" * 50 + "\n")


def test_discord_webhook():
    """Sends a verification test embed to the configured Discord webhook."""
    if not settings.is_discord_configured:
        print("⚠️ DISCORD_WEBHOOK_URL não está configurada em seu arquivo .env!")
        return

    print("Enviando mensagem de teste rica para o Discord...")
    from tools.steam_api import SteamClient
    client = SteamClient()
    details = client.get_game_details(2444750) or {}

    success = send_discord_notification(
        title="Shape of Dreams - MENOR PREÇO HISTÓRICO",
        description="O jogo atualmente está no seu menor preço histórico registrado.",
        game_title="Shape of Dreams",
        current_price=24.99,
        historical_low=24.99,
        discount_percent=30,
        initial_price=details.get("initial_price") or 71.99,
        store_url="https://store.steampowered.com/app/2444750/",
        review_summary="96% de aprovação (3.420 análises)",
        header_image=details.get("header_image"),
        icon_url=details.get("icon_url"),
        tags=details.get("genres", ["Action Roguelike", "High Skill Ceiling", "Bullet Hell"]),
        player_modes=details.get("player_modes", ["Um jogador (Singleplayer)", "Co-op Online"]),
        developers=details.get("developers", ["Lizard Smoothie"]),
        publishers=details.get("publishers", ["NEOWIZ"]),
        release_date=details.get("release_date", "10/set./2025"),
        short_description=details.get("short_description", "Shape of Dreams é um jogo único que combina ação roguelite com elementos de MOBA. Aventure-se pelo mundo dos sonhos e crie seu próprio estilo de combate."),
    )
    if success:
        print("✅ Mensagem enviada ao Discord com sucesso! Verifique seu canal.")
    else:
        print("❌ Falha ao enviar mensagem ao Discord. Verifique a URL do webhook.")


def main():
    parser = argparse.ArgumentParser(description="Games Reviewer - Steam AI Assistant Runner")
    parser.add_argument("--mode", choices=["chat", "daemon", "discord"], default="chat", help="Operation mode (chat, daemon, or discord bot)")
    parser.add_argument("--check-now", action="store_true", help="Execute an immediate price and news scan")
    parser.add_argument("--force", action="store_true", help="Force sending alerts even if already notified at current price")
    parser.add_argument("--test-discord", action="store_true", help="Send a test notification to Discord")

    args = parser.parse_args()

    if args.test_discord:
        test_discord_webhook()
    elif args.check_now:
        asyncio.run(run_check_now(force=args.force))
    elif args.mode == "discord":
        from agent.discord_bot import start_discord_bot
        start_discord_bot()
    elif args.mode == "daemon":
        asyncio.run(run_daemon_loop())
    elif args.mode == "chat":
        asyncio.run(run_chat_session())


if __name__ == "__main__":
    main()
