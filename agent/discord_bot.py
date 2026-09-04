"""Interactive Discord Bot for Games Reviewer.

Provides Slash Commands:
- /help: Detailed guide and commands list.
- /tags: Interactive dropdown to select game categories of interest.
- /preco: Interactive selector to set maximum price threshold in BRL.
- /vincular_steam: Links personal Steam wishlist to the community pool.
- /minha_wishlist: Displays games on your wishlist currently at lowest historical price.
- /definir_canal: Configures server announcement channel for alerts.
- /check: Forces immediate scan of all wishlists for lowest historical prices.
- /recomendar: AI game recommendation carousel based on play history.
- /noticias: Gaming news radar filtered by user profile.
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional, List

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks

from config import settings
from tools.preference_manager import (
    pref_manager,
    AVAILABLE_TAGS,
    PRICE_TIERS,
    TAG_EMOJI_MAP,
    PRICE_EMOJI_MAP
)
from tools.steam_api import SteamClient
from tools.itad_api import evaluate_price_alert
from tools.community_reviews import CommunityReviewAnalyzer
from tools.news_radar import NewsRadar

logger = logging.getLogger("GamesReviewer.DiscordBot")

# ==============================================================================
# UI Components (Select Menus & Views)
# ==============================================================================

class TagSelect(discord.ui.Select):
    def __init__(self, current_tags: List[str]):
        options = []
        for tag_id, tag_data in AVAILABLE_TAGS.items():
            options.append(
                discord.SelectOption(
                    label=tag_data["label"],
                    value=tag_id,
                    description=tag_data["description"][:100],
                    default=tag_id in current_tags
                )
            )
        super().__init__(
            placeholder="Selecione os gêneros e estilos de seu interesse...",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        selected_tags = self.values
        pref_manager.update_user_tags(interaction.user.id, selected_tags)
        
        if selected_tags:
            tag_labels = [AVAILABLE_TAGS[t]["label"] for t in selected_tags]
            desc = "✅ **Suas preferências de categorias foram salvas com sucesso!**\n\n"
            desc += "Você será mencionado sempre que um jogo dessas categorias bater o menor preço histórico:\n"
            for lbl in tag_labels:
                desc += f"• {lbl}\n"
        else:
            desc = "ℹ️ Você desmarcou todas as tags. Você receberá alertas de qualquer jogo que respeitar seu teto de preço."

        embed = discord.Embed(
            title="🎯 Tags de Notificação Atualizadas",
            description=desc,
            color=0x2ECC71
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TagSelectView(discord.ui.View):
    def __init__(self, current_tags: List[str]):
        super().__init__(timeout=180)
        self.add_item(TagSelect(current_tags))


class PriceSelect(discord.ui.Select):
    def __init__(self, current_max_price: float):
        options = []
        for tier in PRICE_TIERS:
            is_default = abs(tier["value"] - current_max_price) < 0.01 or (tier["value"] > 99999 and current_max_price > 99999)
            options.append(
                discord.SelectOption(
                    label=tier["label"],
                    value=str(tier["value"]),
                    default=is_default
                )
            )
        super().__init__(
            placeholder="Selecione o teto máximo de preço em Reais (BRL)...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        max_price = float(self.values[0])
        pref_manager.update_user_max_price(interaction.user.id, max_price)

        if max_price > 99999:
            price_text = "Qualquer Preço (Sem Limite)"
        else:
            price_text = f"Até R$ {max_price:.2f}"

        embed = discord.Embed(
            title="💰 Teto de Preço Atualizado",
            description=f"✅ **Seu limite de preço foi configurado para:** `{price_text}`.\n\n"
                        f"O bot apenas mencionará você em promoções que custem até este valor.",
            color=0x3498DB
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class PriceSelectView(discord.ui.View):
    def __init__(self, current_max_price: float):
        super().__init__(timeout=180)
        self.add_item(PriceSelect(current_max_price))


# ==============================================================================
# Bot Setup & App Commands
# ==============================================================================

class GamesReviewerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.review_analyzer = CommunityReviewAnalyzer()
        self.news_radar = NewsRadar()

    async def setup_hook(self):
        # Sync slash commands globally
        logger.info("Sincronizando comandos slash...")
        await self.tree.sync()
        logger.info("Comandos slash sincronizados com sucesso!")
        # Start periodic background cycle
        if not self.periodic_scan_loop.is_running():
            self.periodic_scan_loop.start()

    async def on_ready(self):
        logger.info(f"Bot conectado como: {self.user} (ID: {self.user.id})")
        # Give gateway a moment to receive all GUILD_CREATE packets
        await asyncio.sleep(2.5)
        logger.info(f"Servidores conectados: {len(self.guilds)}")
        for guild in self.guilds:
            try:
                # Clear guild overrides to avoid duplicate slash commands
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            except Exception as e:
                logger.error(f"Erro ao limpar comandos no servidor {guild.id}: {e}")

        await self.tree.sync()
        logger.info("Comandos slash sincronizados globalmente sem duplicações!")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="menores preços na Steam | /help"
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        logger.info(f"O bot foi adicionado ao servidor: '{guild.name}' (ID: {guild.id})!")
        try:
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            await self.tree.sync()
            logger.info(f"Comandos sincronizados para '{guild.name}'!")
        except Exception as e:
            logger.error(f"Erro ao sincronizar comandos ao entrar no servidor: {e}")

    @tasks.loop(seconds=settings.check_interval_seconds)
    async def periodic_scan_loop(self):
        """Autonomous 3-day scan loop posting alerts with direct user mentions."""
        logger.info("Iniciando ciclo periódico autônomo do Bot do Discord...")
        await run_community_price_check(is_periodic=True)

    @periodic_scan_loop.before_loop
    async def before_periodic_scan(self):
        await self.wait_until_ready()
        await asyncio.sleep(5)


bot = GamesReviewerBot()


# ==============================================================================
# Slash Commands Implementation
# ==============================================================================

@bot.tree.command(name="help", description="Guia completo de comandos e recursos do Games Reviewer")
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Games Reviewer - Guia de Comandos",
        description=(
            "Bem-vindo ao assistente inteligente da Steam! Configure suas preferências "
            "para ser notificado **apenas quando jogos do seu gosto atingirem o menor preço histórico**."
        ),
        color=0x5865F2
    )

    embed.add_field(
        name="🎯 Preferências e Notificações",
        value=(
            "`/tags`: Escolha as categorias de jogos que você quer acompanhar (FPS, Automação, Roguelike, etc.).\n"
            "`/preco`: Defina seu teto máximo de orçamento (ex: *Até R$ 20*, *Até R$ 50* ou *Sem Limite*)."
        ),
        inline=False
    )

    embed.add_field(
        name="🛒 Integração com a Steam",
        value=(
            "`/vincular_steam <url_ou_id>`: Conecte sua Wishlist pública da Steam ao servidor.\n"
            "`/minha_wishlist`: Exibe os jogos da sua wishlist no menor preço histórico."
        ),
        inline=False
    )

    embed.add_field(
        name="⚡ Análises e Varredura",
        value=(
            "`/check`: Força uma varredura de menores preços em todas as wishlists cadastradas.\n"
            "`/recomendar [estilo]`: Recomendações de jogos baseadas no seu histórico de jogo.\n"
            "`/noticias`: Exibe notícias selecionadas sobre jogos e atualizações."
        ),
        inline=False
    )

    embed.add_field(
        name="⚙️ Administração",
        value=(
            "`/definir_canal [canal]`: Define o canal oficial para alertas de promoções.\n"
            "`/painel`: Publica o painel de configuração por reações."
        ),
        inline=False
    )

    embed.set_footer(text="Filtro estrito: notificações enviadas apenas no menor preço histórico verificado.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="tags", description="Configura as categorias e gêneros de jogos para notificações")
async def cmd_tags(interaction: discord.Interaction):
    user_pref = pref_manager.get_user_preference(interaction.user.id)
    current_tags = user_pref.get("tags", [])

    embed = discord.Embed(
        title="🎯 Seleção de Categorias de Jogos",
        description=(
            "Selecione no menu abaixo quais tipos de jogos você quer ser notificado.\n\n"
            "Quando um jogo atingir o **menor preço histórico**, o bot mencionará você diretamente no canal!"
        ),
        color=0x2ECC71
    )
    view = TagSelectView(current_tags)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="preco", description="Define o limite máximo de preço para receber notificações")
async def cmd_preco(interaction: discord.Interaction):
    user_pref = pref_manager.get_user_preference(interaction.user.id)
    current_max = user_pref.get("max_price", 999999.0)

    embed = discord.Embed(
        title="💰 Filtro de Faixa de Preço",
        description=(
            "Escolha o valor máximo que você aceita pagar em uma promoção.\n\n"
            "Se um jogo atingir o menor preço histórico, mas custar mais que o seu teto, "
            "você **não será incomodado**."
        ),
        color=0x3498DB
    )
    view = PriceSelectView(current_max)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


@bot.tree.command(name="vincular_steam", description="Vincula sua Wishlist da Steam para monitoramento de promoções")
@app_commands.describe(perfil_ou_url="Seu ID Steam, nome de usuário ou link do perfil (ex: davii123)")
async def cmd_vincular_steam(interaction: discord.Interaction, perfil_ou_url: str):
    await interaction.response.defer(ephemeral=True)

    # Clean vanity or url
    cleaned = perfil_ou_url.strip()
    match = re.search(r'steamcommunity\.com/id/([^/?\s]+)', cleaned) or re.search(r'steamcommunity\.com/profiles/(\d+)', cleaned)
    vanity = match.group(1) if match else cleaned

    client = SteamClient(user_id=vanity)
    wishlist = client.get_wishlist()

    pref_manager.set_user_steam_id(interaction.user.id, vanity)

    embed = discord.Embed(
        title="✅ Wishlist da Steam Vinculada!",
        description=(
            f"Perfil vinculado: **{vanity}**\n"
            f"Total de jogos detectados na Wishlist: **{len(wishlist)}**\n\n"
            "Sua lista foi adicionada ao ciclo de monitoramento comunitário do servidor. "
            "Sempre que algum jogo da sua lista atingir o menor preço histórico, você será avisado!"
        ),
        color=0x5865F2
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="minha_wishlist", description="Exibe os jogos da sua Wishlist que estão no menor preço histórico")
async def cmd_minha_wishlist(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_pref = pref_manager.get_user_preference(interaction.user.id)
    steam_id = user_pref.get("steam_id") or settings.steam_user_id

    client = SteamClient(user_id=steam_id)
    wishlist = await asyncio.to_thread(client.get_wishlist)

    if not wishlist:
        await interaction.followup.send(
            "⚠️ Nenhuma wishlist encontrada ou perfil privado. Use `/vincular_steam` para cadastrar um perfil público.",
            ephemeral=True
        )
        return

    discounted_items = [
        item for item in wishlist
        if item.get("discount_percent", 0) > 0 and item.get("current_price", 0) > 0
    ]

    historical_deals = []
    for item in discounted_items:
        appid = item.get("appid")
        name = item.get("name", "Unknown")
        current_price = item.get("current_price", 0.0)
        discount = item.get("discount_percent", 0)

        price_eval = await asyncio.to_thread(
            evaluate_price_alert,
            game_title=name,
            current_price=current_price,
            discount_percent=discount,
            appid=appid
        )

        if price_eval.get("trigger_alert"):
            details = await asyncio.to_thread(client.get_game_details, appid)
            game_tags = details.get("tags", item.get("tags", [])) if details else item.get("tags", [])
            header_img = (details.get("header_image") if details else None) or item.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"

            consensus = await asyncio.to_thread(bot.review_analyzer.summarize_game_consensus, appid, name)
            score_desc = consensus.get("score_desc", "Muito Positivas")
            pos_pct = consensus.get("positive_percent", 0)

            end_info = await asyncio.to_thread(client.get_discount_end_info, appid)
            promo_end_text = end_info.get("text", "Promoção por tempo limitado")
            store_url = item.get("store_url") or f"https://store.steampowered.com/app/{appid}/"

            historical_deals.append({
                "name": name,
                "appid": appid,
                "current_price": current_price,
                "historical_low": price_eval["historical_low"],
                "discount_percent": discount,
                "store_url": store_url,
                "tags": game_tags,
                "promo_end": promo_end_text,
                "score_desc": score_desc,
                "pos_pct": pos_pct,
                "header_image": header_img
            })

    if not historical_deals:
        embed = discord.Embed(
            title="🔍 Sua Wishlist — Nenhuma Promoção no Menor Preço Histórico",
            description=(
                f"• **Perfil verificado:** `{steam_id}`\n"
                f"• **Jogos avaliados na sua wishlist:** {len(wishlist)}\n\n"
                "Nenhum jogo da sua lista de desejos atingiu o menor preço histórico no momento.\n"
                "Você será notificado automaticamente assim que qualquer título da sua lista bater o recorde de preço!"
            ),
            color=0x95A5A6
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    if len(historical_deals) > 1:
        view = PromoCarouselView(historical_deals)
        await interaction.followup.send(
            content=f"🎯 **Sua Wishlist: {len(historical_deals)} jogos no Menor Preço Histórico!**\nNavegue pelas ofertas no carrossel abaixo:",
            embed=view.create_embed(),
            view=view,
            ephemeral=True
        )
    else:
        embed = create_deal_embed(historical_deals[0])
        await interaction.followup.send(
            content="🎯 **Sua Wishlist: 1 jogo no Menor Preço Histórico!**",
            embed=embed,
            ephemeral=True
        )


@bot.tree.command(name="definir_canal", description="Define o canal oficial para envio dos alertas de promoções")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(canal="Canal para os anúncios (opcional: deixe em branco para usar o canal atual onde você está)")
async def cmd_definir_canal(interaction: discord.Interaction, canal: Optional[discord.abc.GuildChannel] = None):
    if interaction.user.guild_permissions and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Apenas administradores do servidor podem usar este comando.", ephemeral=True)
        return

    target = canal or interaction.channel
    if not target or not hasattr(target, "id"):
        await interaction.response.send_message("❌ Não foi possível identificar o canal. Execute o comando dentro de um canal de texto.", ephemeral=True)
        return

    guild_id = interaction.guild_id or (interaction.guild.id if interaction.guild else None)
    if not guild_id:
        await interaction.response.send_message("❌ Este comando deve ser executado dentro de um servidor.", ephemeral=True)
        return

    pref_manager.set_announcement_channel(guild_id, target.id)
    embed = discord.Embed(
        title="📢 Canal de Alertas Configurado com Sucesso!",
        description=f"O canal {target.mention} foi definido como o canal oficial de notificações de **Menor Preço Histórico**!",
        color=0x2ECC71
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="painel", description="Publica o painel de preferências e categorias por reações")
async def cmd_painel(interaction: discord.Interaction):
    if interaction.user.guild_permissions and not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ Apenas administradores ou moderadores com permissão de 'Gerenciar Canais' podem publicar o painel.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # --------------------------------------------------------------------------
    # Mensagem 1: Categorias de Ação & Sobrevivência (6 Tags Oficiais Steam)
    # --------------------------------------------------------------------------
    group1_tags = ["action", "adventure", "survival", "pvp", "rpg", "horror"]
    group1_lines = []
    group1_emojis = []
    for emoji, tag_key in TAG_EMOJI_MAP.items():
        if tag_key in group1_tags and (tag_info := AVAILABLE_TAGS.get(tag_key)):
            group1_lines.append(f"{emoji} • **{tag_info['label'].split(' ', 1)[1]}** — {tag_info['description']}")
            group1_emojis.append(emoji)

    embed_cat1 = discord.Embed(
        title="🎮 Preferências: Ação, Aventura & Sobrevivência",
        description=(
            "Reaja aos emojis abaixo para receber alertas quando jogos destes estilos atingirem o menor preço histórico:\n\n"
            + "\n".join(group1_lines)
        ),
        color=0x5865F2
    )
    embed_cat1.set_footer(text="Reaja abaixo para ativar ou desativar cada categoria.")
    msg_cat1 = await interaction.channel.send(embed=embed_cat1)

    # --------------------------------------------------------------------------
    # Mensagem 2: Categorias de Estratégia, Lógica & Indie (6 Tags Oficiais Steam)
    # --------------------------------------------------------------------------
    group2_tags = ["strategy", "puzzle", "indie", "roguelike", "management", "tower_defense"]
    group2_lines = []
    group2_emojis = []
    for emoji, tag_key in TAG_EMOJI_MAP.items():
        if tag_key in group2_tags and (tag_info := AVAILABLE_TAGS.get(tag_key)):
            group2_lines.append(f"{emoji} • **{tag_info['label'].split(' ', 1)[1]}** — {tag_info['description']}")
            group2_emojis.append(emoji)

    embed_cat2 = discord.Embed(
        title="♟️ Preferências: Estratégia, Lógica & Indie",
        description=(
            "Reaja aos emojis abaixo para habilitar notificações das seguintes categorias:\n\n"
            + "\n".join(group2_lines)
        ),
        color=0x3498DB
    )
    embed_cat2.set_footer(text="Reaja abaixo para ativar ou desativar cada categoria.")
    msg_cat2 = await interaction.channel.send(embed=embed_cat2)

    # --------------------------------------------------------------------------
    # Mensagem 3: Configuração de Orçamento Máximo
    # --------------------------------------------------------------------------
    price_lines = [
        f"{tier['label']}"
        for tier in PRICE_TIERS
    ]

    embed_budget = discord.Embed(
        title="💰 Filtro de Orçamento Máximo",
        description=(
            "Defina o valor máximo que você aceita pagar em uma promoção. "
            "Você só receberá notificações para jogos dentro deste limite:\n\n"
            + "\n".join(price_lines)
        ),
        color=0x2ECC71
    )
    embed_budget.set_footer(text="Reaja com um emoji para definir seu limite de preço.")
    msg_budget = await interaction.channel.send(embed=embed_budget)

    # Persist all category and budget message IDs for guild routing
    pref_manager.set_panel_messages(interaction.guild_id, [msg_cat1.id, msg_cat2.id], msg_budget.id)

    # --------------------------------------------------------------------------
    # Mensagem 4: Guia Rápido & Comandos Úteis
    # --------------------------------------------------------------------------
    embed_commands = discord.Embed(
        title="⚡ Guia Rápido & Comandos",
        description=(
            "• `/minha_wishlist` — Exibe os jogos da sua wishlist no menor preço histórico.\n"
            "• `/vincular_steam <url>` — Adiciona sua lista de desejos ao radar comunitário.\n"
            "• `/check` — Força uma varredura de menores preços históricos nas wishlists.\n"
            "• `/recomendar [estilo]` — Recomendações de jogos inéditos baseadas no seu histórico de horas.\n"
            "• `/noticias` — Exibe notícias selecionadas sobre jogos e atualizações."
        ),
        color=0xF1C40F
    )
    await interaction.channel.send(embed=embed_commands)

    # Add reactions to Message 1 (6 tags)
    for emoji in group1_emojis:
        try:
            await msg_cat1.add_reaction(emoji)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    # Add reactions to Message 2 (6 tags)
    for emoji in group2_emojis:
        try:
            await msg_cat2.add_reaction(emoji)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    # Add reactions to Message 3 (5 prices)
    for emoji in PRICE_EMOJI_MAP.keys():
        try:
            await msg_budget.add_reaction(emoji)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    await interaction.followup.send(
        f"✅ Painel de 4 mensagens publicado com sucesso em {interaction.channel.mention}!",
        ephemeral=True
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if not payload.guild_id:
        return

    panel_msgs = pref_manager.get_panel_messages(payload.guild_id)
    cat_msg_ids = panel_msgs.get("category_message_ids", [])
    budget_msg_id = panel_msgs.get("budget_message_id")

    if payload.message_id not in cat_msg_ids and payload.message_id != budget_msg_id:
        return

    emoji_str = str(payload.emoji)
    user = bot.get_user(payload.user_id)
    if not user:
        try:
            user = await bot.fetch_user(payload.user_id)
        except Exception:
            user = None

    # Messages 1 & 2: Categories
    if payload.message_id in cat_msg_ids and emoji_str in TAG_EMOJI_MAP:
        tag_id = TAG_EMOJI_MAP[emoji_str]
        pref_manager.add_user_tag(payload.user_id, tag_id)
        tag_label = AVAILABLE_TAGS[tag_id]["label"]
        if user:
            try:
                await user.send(f"🎯 **Categoria Ativada:** Você agora receberá alertas para: **{tag_label}**.")
            except Exception:
                pass

    # Message 3: Budget
    elif payload.message_id == budget_msg_id and emoji_str in PRICE_EMOJI_MAP:
        max_price = PRICE_EMOJI_MAP[emoji_str]
        pref_manager.update_user_max_price(payload.user_id, max_price)
        price_text = f"Até R$ {max_price:.2f}" if max_price < 99999 else "Qualquer Preço (Sem Limite)"
        if user:
            try:
                await user.send(f"💰 **Orçamento Atualizado:** Seu limite de preço foi definido para: **{price_text}**.")
            except Exception:
                pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if not payload.guild_id:
        return

    panel_msgs = pref_manager.get_panel_messages(payload.guild_id)
    cat_msg_ids = panel_msgs.get("category_message_ids", [])

    if payload.message_id in cat_msg_ids:
        emoji_str = str(payload.emoji)
        if emoji_str in TAG_EMOJI_MAP:
            tag_id = TAG_EMOJI_MAP[emoji_str]
            pref_manager.remove_user_tag(payload.user_id, tag_id)
            tag_label = AVAILABLE_TAGS[tag_id]["label"]
            user = bot.get_user(payload.user_id)
            if not user:
                try:
                    user = await bot.fetch_user(payload.user_id)
                except Exception:
                    user = None
            if user:
                try:
                    await user.send(f"❌ **Categoria Removida:** Você não receberá mais alertas para: **{tag_label}**.")
                except Exception:
                    pass


def create_deal_embed(g: dict, page_info: Optional[str] = None) -> discord.Embed:
    """Builds a rich visual embed card for a game on historical low sale."""
    name = g.get("name", "Unknown")
    current_price = g.get("current_price", 0.0)
    historical_low = g.get("historical_low", 0.0)
    discount = g.get("discount_percent", 0)
    promo_end = g.get("promo_end", "Promoção por tempo limitado")
    store_url = g.get("store_url", f"https://store.steampowered.com/app/{g.get('appid')}/")
    tags = g.get("tags", [])
    tag_str = ", ".join(tags[:5]) if tags else "Geral"
    score_desc = g.get("score_desc", "Muito Positivas")
    pos_pct = g.get("pos_pct", 90)
    header_img = g.get("header_image")

    is_rec = g.get("is_recommendation", False)
    if is_rec:
        title_prefix = f"💡 RECOMENDAÇÃO HISTÓRICA ({page_info}): " if page_info else "💡 NOVA RECOMENDAÇÃO HISTÓRICA: "
        header_intro = "🎮 **Recomendação baseada nas preferências e wishlists da comunidade!**\nEste título atingiu seu **menor preço histórico já registrado em Reais**!\n\n"
        color = 0x1ABC9C
    else:
        title_prefix = f"🚨 MENOR PREÇO HISTÓRICO ({page_info}): " if page_info else "🚨 NOVO MENOR PREÇO HISTÓRICO: "
        header_intro = "O jogo atingiu ou superou seu **menor preço histórico já registrado em Reais**!\n\n"
        color = 0x2ECC71

    embed = discord.Embed(
        title=f"{title_prefix}{name}",
        description=(
            f"{header_intro}"
            f"💵 **Preço Atual:** R$ {current_price:.2f} `(-{discount}%)`\n"
            f"📉 **Menor Histórico:** R$ {historical_low:.2f}\n"
            f"⏰ **Término da Oferta:** {promo_end}\n"
            f"⭐ **Consenso:** {score_desc} ({pos_pct}% positivas)\n"
            f"🏷️ **Tags:** {tag_str}\n\n"
            f"[Acessar na Loja Steam]({store_url})"
        ),
        color=color,
        timestamp=discord.utils.utcnow()
    )
    if header_img:
        embed.set_image(url=header_img)

    if page_info:
        embed.set_footer(text="Carrossel Interativo • Use os botões abaixo para folhear entre as ofertas!")
    return embed


class PromoCarouselView(discord.ui.View):
    """Interactive lateral scroll carousel for deals exceeding cognitive threshold (X > 4)."""

    def __init__(self, games: List[dict], timeout: Optional[float] = 604800.0):
        super().__init__(timeout=timeout)
        self.games = games
        self.current_page = 0
        self._update_buttons()

    def _update_buttons(self):
        total = len(self.games)
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_counter.label = f"🎮 {self.current_page + 1} de {total}"
        self.btn_next.disabled = (self.current_page >= total - 1)

    def create_embed(self) -> discord.Embed:
        page_info = f"{self.current_page + 1}/{len(self.games)}"
        return create_deal_embed(self.games[self.current_page], page_info=page_info)

    @discord.ui.button(label="◀️ Anterior", style=discord.ButtonStyle.primary, custom_id="carousel_prev")
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="carousel_counter")
    async def btn_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="Próximo ▶️", style=discord.ButtonStyle.primary, custom_id="carousel_next")
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.games) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()


def search_steam_game(title: str) -> dict:
    """Searches Steam Store API for game pricing, appid, and capsule image."""
    try:
        r = requests.get(
            f"https://store.steampowered.com/api/storesearch/?term={requests.utils.quote(title)}&l=brazilian&cc=BR",
            timeout=5
        )
        if r.ok:
            items = r.json().get("items", [])
            if items:
                best = items[0]
                appid = best.get("id")
                price_data = best.get("price")
                if price_data:
                    final_cents = price_data.get("final", 0)
                    init_cents = price_data.get("initial", final_cents)
                    final_price = final_cents / 100
                    disc = round((init_cents - final_cents) / init_cents * 100) if init_cents > final_cents else 0
                    price_txt = f"R$ {final_price:.2f}" if final_price > 0 else "Gratuito"
                else:
                    price_txt = "Gratuito para Jogar"
                    disc = 0
                return {
                    "name": best.get("name", title),
                    "appid": appid,
                    "price_txt": price_txt,
                    "discount_percent": disc,
                    "store_url": f"https://store.steampowered.com/app/{appid}/",
                    "header_image": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                }
    except Exception as e:
        logger.debug(f"Erro ao buscar jogo '{title}' na Steam Store: {e}")

    return {
        "name": title,
        "appid": None,
        "price_txt": "Consultar na Steam",
        "discount_percent": 0,
        "store_url": f"https://store.steampowered.com/search/?term={requests.utils.quote(title)}",
        "header_image": None
    }


class RecommendationCarouselView(discord.ui.View):
    """Interactive lateral scroll carousel for game recommendations."""

    def __init__(self, games: List[dict], timeout: Optional[float] = 604800.0):
        super().__init__(timeout=timeout)
        self.games = games
        self.current_page = 0
        self._update_buttons()

    def _update_buttons(self):
        total = len(self.games)
        self.btn_prev.disabled = (self.current_page == 0)
        self.btn_counter.label = f"🎮 {self.current_page + 1} de {total}"
        self.btn_next.disabled = (self.current_page >= total - 1)

    def create_embed(self) -> discord.Embed:
        g = self.games[self.current_page]
        total = len(self.games)
        page_info = f"{self.current_page + 1} de {total}"
        name = g.get("name", "Jogo Recomendado")
        reason = g.get("reason", "")
        price_txt = g.get("price_txt", "Consultar na Steam")
        disc_txt = f" `(-{g['discount_percent']}%)`" if g.get("discount_percent", 0) > 0 else ""
        store_url = g.get("store_url", f"https://store.steampowered.com/search/?term={requests.utils.quote(name)}")
        header_img = g.get("header_image")

        embed = discord.Embed(
            title=f"💡 Recomendação ({page_info}): {name}",
            description=(
                f"**Por que vale a pena:** {reason}\n\n"
                f"💵 **Preço na Steam:** {price_txt}{disc_txt}\n\n"
                f"🔗 [Acessar na Loja Steam]({store_url})"
            ),
            color=0x1ABC9C
        )
        if header_img:
            embed.set_image(url=header_img)
        embed.set_footer(text="Carrossel Interativo • Use os botões abaixo para folhear entre as recomendações!")
        return embed

    @discord.ui.button(label="◀️ Anterior", style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="Próximo ▶️", style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.games) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)
        else:
            await interaction.response.defer()


@bot.tree.command(name="check", description="Verifica promoções ativas no menor preço histórico nas wishlists")
async def cmd_check(interaction: discord.Interaction):
    await interaction.response.defer()
    results = await run_community_price_check(is_periodic=False)
    games = results.get("games", [])

    if not games:
        embed = discord.Embed(
            title="🔍 Varredura Concluída - Nenhuma Promoção Histórica",
            description=(
                f"• **Wishlists verificadas:** {results['profiles_scanned']}\n"
                f"• **Jogos avaliados:** {results['games_evaluated']}\n\n"
                "Nenhum jogo da sua lista está atualmente no menor preço histórico ou com desconto ativo."
            ),
            color=0x95A5A6
        )
        await interaction.followup.send(embed=embed)
        return

    # If more than 4 deals, use the lateral scroll carousel to avoid notification fatigue
    if len(games) > 4:
        all_pings = set()
        for g in games:
            all_pings.update(g.get("users_to_ping", []))
        mention_str = f"\n🔔 **Membros notificados:** " + " ".join(f"<@{uid}>" for uid in all_pings) if all_pings else ""
        content = (
            f"🚨 **Varredura Concluída: {len(games)} jogos no Menor Preço Histórico!**\n"
            f"Navegue pelas ofertas completas no carrossel abaixo:{mention_str}"
        )
        view = PromoCarouselView(games)
        await interaction.followup.send(content=content, embed=view.create_embed(), view=view)
    else:
        for g in games:
            embed = create_deal_embed(g)
            await interaction.followup.send(embed=embed)


@bot.tree.command(name="noticias", description="Exibe notícias selecionadas sobre jogos e atualizações")
async def cmd_noticias(interaction: discord.Interaction):
    await interaction.response.defer()
    news = bot.news_radar.get_relevant_news(min_score=2, max_items=4)

    if not news:
        await interaction.followup.send("Nenhuma notícia de alta afinidade no momento.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📰 Radar de Notícias Gamer",
        description="Manchetes filtradas com foco em precisão mecânica, e-sports táticos e lógica/automação:",
        color=0x9B59B6
    )

    for item in news:
        embed.add_field(
            name=f"[{item['source']}] {item['title']}",
            value=f"{item['summary'][:180]}...\n[Ler matéria completa]({item['link']})",
            inline=False
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="recomendar", description="Recomendações de jogos inéditos baseadas no seu perfil em formato carrossel")
@app_commands.describe(estilo="Gênero ou características desejadas (ex: shooter tático, roguelike, estratégia)")
async def cmd_recomendar(interaction: discord.Interaction, estilo: Optional[str] = None):
    await interaction.response.defer()
    query = estilo or "jogos com boa progressão e jogabilidade marcante"

    user_pref = pref_manager.get_user_preference(interaction.user.id)
    steam_id = user_pref.get("steam_id") or settings.steam_user_id
    steam_client = SteamClient(user_id=steam_id)

    # 1. Real owned games with actual playtime (> 0 hours)
    owned_games = await asyncio.to_thread(steam_client.get_owned_games)
    owned_played = [g for g in owned_games if g.get("playtime_forever", 0) > 0]
    owned_sorted = sorted(owned_played, key=lambda x: x.get("playtime_forever", 0), reverse=True)
    top_played = [
        f"{g['name']} ({round(g.get('playtime_forever', 0) / 60, 1)}h)"
        for g in owned_sorted[:8] if g.get("name")
    ]
    all_owned_names = [g.get("name", "").strip() for g in owned_games if g.get("name")]

    top_played_str = ", ".join(top_played) if top_played else "Counter-Strike 2 (1266h), Warframe (815h), Palworld (584h)"

    prompt = f"""Você é um amigo gamer experiente que conhece muito bem o catálogo da Steam.
Analise os jogos mais jogados do jogador para entender o gosto dele:
{top_played_str}

{f"O jogador pediu recomendações focadas em: '{query}'." if query and query != "jogos com boa progressão e jogabilidade marcante" else ""}

JOGOS QUE O JOGADOR JÁ POSSUI (É RIGOROSAMENTE PROIBIDO RECOMENDAR QUALQUER UM DESTES):
{', '.join(sorted(all_owned_names))}

INSTRUÇÕES RIGOROSAS DE TOM E FORMATO:
1. Use uma linguagem casual, humana, amigável e direta (como dois amigos conversando no Discord).
2. NUNCA use clichês corporativos ou sensacionalistas de IA. É terminantemente proibido usar termos como:
   - "se alinham diretamente com"
   - "precisão cirúrgica"
   - "alta afinidade mecânica"
   - "análise algorítmica"
   - "experiência visceral"
   - "rigoroso" ou "consenso de pessoas reais"
3. Prefira termos naturais como: "se parecem com", "têm uma pegada parecida com o que você curte", "lembram um pouco", "misturam elementos de".
4. NÃO liste os nomes dos jogos do histórico do jogador na justificativa. Mantenha o histórico oculto do texto final.
5. No campo 'justificativa', complete a frase iniciando obrigatoriamente por:
   "Baseado no seu histórico, as seguintes recomendações são feitas, pois [sua explicação casual e humana em 1 ou 2 frases sem listar os jogos do perfil]".
6. Selecione 3 jogos inéditos que realmente combinem com o gosto do jogador. Para cada jogo, informe o nome oficial na Steam e uma breve justificativa amigável e casual em 'reason' (1 a 2 frases) explicando por que vale a pena.

Responda OBRIGATORIAMENTE em formato JSON válido:
{{
  "justificativa": "Baseado no seu histórico, as seguintes recomendações são feitas, pois ...",
  "games": [
    {{
      "name": "Nome do Jogo na Steam",
      "reason": "Por que vale a pena..."
    }}
  ]
}}
"""

    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.6-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        data = json.loads(resp.text)
        justification = data.get("justificativa", "").strip()
        recommended_raw = data.get("games", [])
    except Exception as e:
        logger.error(f"Erro ao gerar recomendação via Gemini: {e}")
        justification = (
            "Baseado no seu histórico, as seguintes recomendações são feitas, pois você claramente curte "
            "jogos dinâmicos, com progressão envolvente e um gameplay que te prende por horas."
        )
        recommended_raw = [
            {"name": "Risk of Rain 2", "reason": "Tem uma ação frenética em terceira pessoa, jogabilidade rápida e muitas combinações de itens."},
            {"name": "Dead Cells", "reason": "Combate 2D muito fluido e responsivo, com uma variedade enorme de armas pra testar a cada tentativa."},
            {"name": "Deep Rock Galactic", "reason": "Cooperação excelente com amigos, exploração de mapas dinâmicos e muita ação sem enrolação."}
        ]

    prefix = "Baseado no seu histórico, as seguintes recomendações são feitas, pois"
    if not justification.startswith(prefix):
        if "pois" in justification.lower():
            after_pois = justification.split("pois", 1)[1].strip()
            justification = f"{prefix} {after_pois}"
        else:
            justification = f"{prefix} combinam com os estilos de jogos nos quais você mais investe tempo."

    enriched_games = []
    for g in recommended_raw[:4]:
        name = g.get("name", "").strip()
        if not name:
            continue
        steam_data = await asyncio.to_thread(search_steam_game, name)
        steam_data["reason"] = g.get("reason", "").strip()
        enriched_games.append(steam_data)

    if not enriched_games:
        enriched_games = [
            {
                "name": "Risk of Rain 2",
                "appid": 632360,
                "price_txt": "R$ 59.99",
                "discount_percent": 0,
                "store_url": "https://store.steampowered.com/app/632360/",
                "header_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/632360/header.jpg",
                "reason": "Tem uma ação dinâmica em terceira pessoa com ótimas sinergias de itens."
            }
        ]

    view = RecommendationCarouselView(enriched_games)
    await interaction.followup.send(
        content=justification,
        embed=view.create_embed(),
        view=view
    )


# ==============================================================================
# Community Price Scanner & Mention Engine
# ==============================================================================

async def run_community_price_check(is_periodic: bool = False, source_channel: Optional[discord.TextChannel] = None) -> dict:
    """Scans all registered community wishlists, cleans expired alerts, and dispatches new alerts."""
    # 1. Clean up expired alerts from Discord announcement channels
    active_alerts = pref_manager.get_active_alerts()
    if active_alerts:
        logger.info(f"Verificando {len(active_alerts)} alertas ativos para remoção de promoções expiradas...")
        cleaner_client = SteamClient()
        for alert in list(active_alerts):
            aid = alert.get("appid")
            cid = alert.get("channel_id")
            mid = alert.get("message_id")
            try:
                details = await asyncio.to_thread(cleaner_client.get_app_details, aid)
                # If game is no longer discounted or no longer available, delete the message
                if not details or details.get("discount_percent", 0) == 0:
                    ch = bot.get_channel(cid)
                    if ch:
                        try:
                            msg_to_del = await ch.fetch_message(mid)
                            await msg_to_del.delete()
                            logger.info(f"Promoção expirada! Mensagem apagada do chat para: {alert.get('name')} (ID: {mid})")
                        except Exception as e:
                            logger.debug(f"Não foi possível apagar mensagem {mid}: {e}")
                    pref_manager.remove_active_alert(mid)
            except Exception as e:
                logger.error(f"Erro ao verificar expiração de {aid}: {e}")

    # 2. Scan wishlists for new lowest price records
    community_ids = pref_manager.get_all_community_steam_ids()
    if settings.steam_user_id not in community_ids:
        community_ids.append(settings.steam_user_id)

    analyzer = bot.review_analyzer
    silent_skips = 0
    games_evaluated = 0
    triggered_games = []
    seen_appids = set()

    for steam_id in community_ids:
        client = SteamClient(user_id=steam_id)
        wishlist = client.get_wishlist()

        for item in wishlist:
            appid = item.get("appid")
            if not appid or appid in seen_appids:
                continue
            seen_appids.add(appid)

            current_price = item.get("current_price", 0.0)
            discount = item.get("discount_percent", 0)
            name = item.get("name", "Unknown")
            tags = item.get("tags", [])

            if discount > 0 and current_price > 0:
                games_evaluated += 1
                price_eval = evaluate_price_alert(
                    game_title=name,
                    current_price=current_price,
                    discount_percent=discount,
                    appid=appid
                )

                if price_eval.get("trigger_alert"):
                    # Enrich with real game details: banner image and store tags
                    details = await asyncio.to_thread(client.get_game_details, appid)
                    game_tags = details.get("tags", tags) if details else tags
                    header_img = (details.get("header_image") if details else None) or item.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"

                    consensus = await asyncio.to_thread(analyzer.summarize_game_consensus, appid, name)
                    score_desc = consensus.get("score_desc", "Muito Positivas")
                    pos_pct = consensus.get("positive_percent", 0)

                    # Fetch promotion end date
                    end_info = await asyncio.to_thread(client.get_discount_end_info, appid)
                    promo_end_text = end_info.get("text", "Promoção por tempo limitado")

                    users_to_ping = pref_manager.find_users_to_notify(game_tags, current_price)
                    store_url = item.get("store_url") or f"https://store.steampowered.com/app/{appid}/"

                    game_data = {
                        "name": name,
                        "appid": appid,
                        "current_price": current_price,
                        "historical_low": price_eval["historical_low"],
                        "discount_percent": discount,
                        "store_url": store_url,
                        "tags": game_tags,
                        "users_to_ping": users_to_ping,
                        "promo_end": promo_end_text,
                        "header_image": header_img,
                        "score_desc": score_desc,
                        "pos_pct": pos_pct
                    }
                    triggered_games.append(game_data)
                else:
                    silent_skips += 1

    # 2.5 Use wishlists as database to discover new recommendations on historical low
    try:
        community_tags_pool = set()
        for steam_id in community_ids:
            c = SteamClient(user_id=steam_id)
            w = c.get_wishlist()
            for itm in w:
                for tg in itm.get("tags", []):
                    community_tags_pool.add(tg.lower())

        steam_specials = await asyncio.to_thread(client.get_featured_specials)
        for sp in steam_specials:
            sp_appid = sp.get("appid")
            if not sp_appid or sp_appid in seen_appids:
                continue
            seen_appids.add(sp_appid)

            sp_price = sp.get("current_price", 0.0)
            sp_disc = sp.get("discount_percent", 0)
            sp_name = sp.get("name", "Unknown")

            if sp_disc > 0 and sp_price > 0:
                games_evaluated += 1
                sp_eval = evaluate_price_alert(
                    game_title=sp_name,
                    current_price=sp_price,
                    discount_percent=sp_disc,
                    appid=sp_appid
                )
                if sp_eval.get("trigger_alert"):
                    details = await asyncio.to_thread(client.get_game_details, sp_appid)
                    game_tags = details.get("tags", []) if details else []
                    users_to_ping = pref_manager.find_users_to_notify(game_tags, sp_price)

                    # Recommend if there is tag overlap with the community wishlists pool or subscribed user tags
                    has_overlap = any(t.lower() in community_tags_pool for t in game_tags) or bool(users_to_ping)
                    if has_overlap:
                        header_img = (details.get("header_image") if details else None) or sp.get("header_image") or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{sp_appid}/header.jpg"
                        consensus = await asyncio.to_thread(analyzer.summarize_game_consensus, sp_appid, sp_name)
                        score_desc = consensus.get("score_desc", "Muito Positivas")
                        pos_pct = consensus.get("positive_percent", 0)

                        end_info = await asyncio.to_thread(client.get_discount_end_info, sp_appid)
                        promo_end_text = end_info.get("text", "Promoção por tempo limitado")
                        store_url = f"https://store.steampowered.com/app/{sp_appid}/"

                        rec_data = {
                            "name": sp_name,
                            "appid": sp_appid,
                            "current_price": sp_price,
                            "historical_low": sp_eval["historical_low"],
                            "discount_percent": sp_disc,
                            "store_url": store_url,
                            "tags": game_tags,
                            "users_to_ping": users_to_ping,
                            "promo_end": promo_end_text,
                            "header_image": header_img,
                            "score_desc": score_desc,
                            "pos_pct": pos_pct,
                            "is_recommendation": True
                        }
                        triggered_games.append(rec_data)
    except Exception as e:
        logger.warning(f"Erro ao avaliar recomendações automáticas baseadas em wishlists: {e}")

    # 3. Dispatch to announcement channels with cognitive load control (Threshold X = 4)
    if is_periodic and triggered_games:
        for guild in bot.guilds:
            ch_id = pref_manager.get_announcement_channel(guild.id)
            if not ch_id:
                continue
            ch = guild.get_channel(ch_id)
            if not ch:
                continue

            # Case A: <= 4 games -> Send individual visual cards with banner images
            if len(triggered_games) <= 4:
                for g in triggered_games:
                    embed = create_deal_embed(g)
                    mention_str = ""
                    if g.get("users_to_ping"):
                        mentions = [f"<@{uid}>" for uid in g["users_to_ping"]]
                        mention_str = f"🔔 **Notificando membros interessados ({len(mentions)}):** " + " ".join(mentions)

                    try:
                        sent_msg = await ch.send(content=mention_str if mention_str else None, embed=embed)
                        pref_manager.save_active_alert({
                            "message_id": sent_msg.id,
                            "channel_id": ch.id,
                            "guild_id": guild.id,
                            "appid": g["appid"],
                            "name": g["name"],
                            "posted_at": datetime.utcnow().isoformat()
                        })
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Erro ao postar alerta no canal {ch.id}: {e}")

            # Case B: > 4 games -> Consolidated Lateral Scroll Carousel (Nelson Cowan 4-item memory limit)
            else:
                all_pings = set()
                for g in triggered_games:
                    all_pings.update(g.get("users_to_ping", []))

                mention_str = ""
                if all_pings:
                    mentions = [f"<@{uid}>" for uid in all_pings]
                    mention_str = f"\n🔔 **Membros notificados:** " + " ".join(mentions)

                content_header = (
                    f"🚨 **Alerta de Menor Preço Histórico — {len(triggered_games)} Ofertas Detectadas!**\n"
                    f"Use o carrossel abaixo para navegar entre todas as ofertas:{mention_str}"
                )

                view = PromoCarouselView(triggered_games)
                try:
                    sent_msg = await ch.send(content=content_header, embed=view.create_embed(), view=view)
                    for g in triggered_games:
                        pref_manager.save_active_alert({
                            "message_id": sent_msg.id,
                            "channel_id": ch.id,
                            "guild_id": guild.id,
                            "appid": g["appid"],
                            "name": g["name"],
                            "posted_at": datetime.utcnow().isoformat()
                        })
                except Exception as e:
                    logger.error(f"Erro ao postar carrossel no canal {ch.id}: {e}")

    return {
        "profiles_scanned": len(community_ids),
        "games_evaluated": games_evaluated,
        "alerts_fired": len(triggered_games),
        "silent_skips": silent_skips,
        "games": triggered_games
    }


def start_discord_bot():
    """Starts the interactive Discord bot."""
    if not settings.is_discord_bot_configured:
        print("\n" + "=" * 60)
        print("⚠️  ERRO: DISCORD_BOT_TOKEN não foi detectado no arquivo .env!")
        print("Para obter e cadastrar seu token:")
        print("1. Acesse: https://discord.com/developers/applications")
        print("2. Crie uma aplicação > aba Bot > copie seu Token.")
        print("3. Adicione a linha no seu arquivo 'Games Reviewer/.env':")
        print("   DISCORD_BOT_TOKEN=seu_token_aqui")
        print("=" * 60 + "\n")
        return

    logger.info("Iniciando Games Reviewer Discord Bot...")
    bot.run(settings.discord_bot_token)
