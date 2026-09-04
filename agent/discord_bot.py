"""Interactive Discord Bot for Games Reviewer.

Provides Slash Commands:
- /help: Detailed guide and commands list.
- /tags: Interactive dropdown to select game categories of interest.
- /preco: Interactive selector to set maximum price threshold in BRL.
- /vincular_steam: Links personal Steam wishlist to the community pool.
- /minha_wishlist: Displays linked wishlist items, prices, and discounts.
- /definir_canal: Configures server announcement channel for alerts.
- /check: Forces immediate scan of all wishlists for lowest historical prices.
- /recomendar: AI game recommendation based on community consensus.
- /reviews: Community review and sentiment summary for any game.
- /noticias: Gaming news radar filtered by user profile.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional, List

import discord
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
            "`/minha_wishlist`: Visualize os jogos da sua wishlist com preços e descontos atuais."
        ),
        inline=False
    )

    embed.add_field(
        name="⚡ Análises e Varredura",
        value=(
            "`/check`: Força uma varredura de menores preços em todas as wishlists cadastradas.\n"
            "`/reviews <jogo>`: Recomendações e análises feitas pela comunidade Steam e Reddit.\n"
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


@bot.tree.command(name="preco", description="Define o limite máximo de preço (BRL) para receber notificações")
async def cmd_preco(interaction: discord.Interaction):
    user_pref = pref_manager.get_user_preference(interaction.user.id)
    current_max = user_pref.get("max_price", 999999.0)

    embed = discord.Embed(
        title="💰 Filtro de Faixa de Preço (BRL)",
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


@bot.tree.command(name="minha_wishlist", description="Exibe os jogos da sua Wishlist cadastrada com preços em R$")
async def cmd_minha_wishlist(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user_pref = pref_manager.get_user_preference(interaction.user.id)
    steam_id = user_pref.get("steam_id") or settings.steam_user_id

    client = SteamClient(user_id=steam_id)
    wishlist = client.get_wishlist()

    if not wishlist:
        await interaction.followup.send(
            "⚠️ Nenhuma wishlist encontrada ou perfil privado. Use `/vincular_steam` para cadastrar um perfil público.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"🛒 Wishlist Steam - {steam_id}",
        description=f"Exibindo os primeiros jogos da lista ({len(wishlist)} títulos no total):",
        color=0x1B2838
    )

    for item in wishlist[:8]:
        price_txt = f"R$ {item['current_price']:.2f}" if item['current_price'] > 0 else "Gratuito"
        disc_txt = f" (-{item['discount_percent']}%)" if item['discount_percent'] > 0 else ""
        embed.add_field(
            name=f"🎮 {item['name']}",
            value=f"Preço: **{price_txt}**{disc_txt} | Avaliações: {item.get('review_desc', 'Positivas')}",
            inline=False
        )

    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="definir_canal", description="Define o canal oficial para envio dos alertas de promoções")
@app_commands.describe(canal="Canal para os anúncios (opcional: deixe em branco para usar o canal atual onde você está)")
async def cmd_definir_canal(interaction: discord.Interaction, canal: Optional[discord.abc.GuildChannel] = None):
    if interaction.user.guild_permissions and not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ Apenas administradores ou moderadores com permissão de 'Gerenciar Canais' podem usar este comando.", ephemeral=True)
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
    # Mensagem 1: Configuração de Categoria de Jogos (12 Tags Oficiais Steam)
    # --------------------------------------------------------------------------
    tag_lines = [
        f"{emoji} • **{tag_info['label'].split(' ', 1)[1]}** — {tag_info['description']}"
        for emoji, tag_key in TAG_EMOJI_MAP.items()
        if (tag_info := AVAILABLE_TAGS.get(tag_key))
    ]

    embed_categories = discord.Embed(
        title="🎮 Games Reviewer — Painel de Alertas",
        description=(
            "Configure suas preferências de notificação reagindo aos emojis abaixo. "
            "Você receberá alertas personalizados quando os jogos de seu gosto estiverem no menor preço historico.\n\n"
            + "\n".join(tag_lines)
        ),
        color=0x5865F2
    )
    embed_categories.set_footer(text="Reaja abaixo com os emojis das categorias que você deseja acompanhar.")
    msg_cat = await interaction.channel.send(embed=embed_categories)

    # --------------------------------------------------------------------------
    # Mensagem 2: Configuração de Orçamento
    # --------------------------------------------------------------------------
    price_lines = [
        f"{tier['label']}"
        for tier in PRICE_TIERS
    ]

    embed_budget = discord.Embed(
        title="💰 Configuração de Orçamento",
        description=(
            "Defina seu teto máximo de preço reagindo aos emojis abaixo. "
            "O bot só notificará você se a promoção estiver dentro deste limite:\n\n"
            + "\n".join(price_lines)
        ),
        color=0x2ECC71
    )
    embed_budget.set_footer(text="Reaja abaixo para definir seu limite de preço máximo em R$.")
    msg_budget = await interaction.channel.send(embed=embed_budget)

    # Persist both message IDs for guild routing
    pref_manager.set_panel_messages(interaction.guild_id, msg_cat.id, msg_budget.id)

    # --------------------------------------------------------------------------
    # Mensagem 3: Comandos Úteis & Funcionamento
    # --------------------------------------------------------------------------
    embed_commands = discord.Embed(
        title="⚡ Comandos Úteis & Funcionamento",
        description=(
            "• `/minha_wishlist` — Exibe os jogos da sua wishlist com preços e descontos em R$.\n"
            "• `/vincular_steam <url>` — Adiciona sua lista de desejos ao radar comunitário.\n"
            "• `/check` — Força uma varredura de menores preços históricos nas wishlists.\n"
            "• `/recomendar [estilo]` — Recomendações de jogos inéditos baseadas no seu histórico de horas.\n"
            "• `/reviews <jogo>` — Recomendações e análises feitas pela comunidade Steam e Reddit.\n"
            "• `/noticias` — Exibe notícias selecionadas sobre jogos e atualizações.\n"
            "• `/definir_canal` — Define o canal oficial para os alertas de promoções.\n\n"
            "🛡️ **Filtro de Menor Preço Histórico (Zero Spam):**\n"
            "O bot monitora os preços cruzando dados com bases históricas de promoções. "
            "Se uma promoção não atingir o menor preço histórico registrado, nenhuma notificação é enviada."
        ),
        color=0xF1C40F
    )
    await interaction.channel.send(embed=embed_commands)

    # Add reactions to Message 1 (12 tags)
    for emoji in TAG_EMOJI_MAP.keys():
        try:
            await msg_cat.add_reaction(emoji)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    # Add reactions to Message 2 (5 prices)
    for emoji in PRICE_EMOJI_MAP.keys():
        try:
            await msg_budget.add_reaction(emoji)
            await asyncio.sleep(0.3)
        except Exception:
            pass

    await interaction.followup.send(
        f"✅ Painel de 3 mensagens publicado com sucesso em {interaction.channel.mention}!",
        ephemeral=True
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if not payload.guild_id:
        return

    panel_msgs = pref_manager.get_panel_messages(payload.guild_id)
    cat_msg_id = panel_msgs.get("category_message_id")
    budget_msg_id = panel_msgs.get("budget_message_id")

    if payload.message_id not in (cat_msg_id, budget_msg_id):
        return

    emoji_str = str(payload.emoji)
    user = bot.get_user(payload.user_id)
    if not user:
        try:
            user = await bot.fetch_user(payload.user_id)
        except Exception:
            user = None

    # Message 1: Categories
    if payload.message_id == cat_msg_id and emoji_str in TAG_EMOJI_MAP:
        tag_id = TAG_EMOJI_MAP[emoji_str]
        pref_manager.add_user_tag(payload.user_id, tag_id)
        tag_label = AVAILABLE_TAGS[tag_id]["label"]
        if user:
            try:
                await user.send(f"🎯 **Categoria Ativada!** Você agora receberá alertas para: **{tag_label}**.")
            except Exception:
                pass

    # Message 2: Budget
    elif payload.message_id == budget_msg_id and emoji_str in PRICE_EMOJI_MAP:
        max_price = PRICE_EMOJI_MAP[emoji_str]
        pref_manager.update_user_max_price(payload.user_id, max_price)
        price_text = f"Até R$ {max_price:.2f}" if max_price < 99999 else "Qualquer Preço (Sem Limite)"
        if user:
            try:
                await user.send(f"💰 **Orçamento Atualizado!** Seu limite de preço foi definido para: **{price_text}**.")
            except Exception:
                pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return

    if not payload.guild_id:
        return

    panel_msgs = pref_manager.get_panel_messages(payload.guild_id)
    cat_msg_id = panel_msgs.get("category_message_id")

    if payload.message_id == cat_msg_id:
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

    title_prefix = f"🚨 MENOR PREÇO HISTÓRICO ({page_info}): " if page_info else "🚨 NOVO MENOR PREÇO HISTÓRICO: "
    embed = discord.Embed(
        title=f"{title_prefix}{name}",
        description=(
            f"O jogo atingiu ou superou seu **menor preço histórico já registrado em Reais**!\n\n"
            f"💵 **Preço Atual:** R$ {current_price:.2f} `(-{discount}%)`\n"
            f"📉 **Menor Histórico:** R$ {historical_low:.2f}\n"
            f"⏰ **Término da Oferta:** {promo_end}\n"
            f"⭐ **Consenso:** {score_desc} ({pos_pct}% positivas)\n"
            f"🏷️ **Tags:** {tag_str}\n\n"
            f"[Acessar na Loja Steam]({store_url})"
        ),
        color=0x2ECC71,
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
            f"Navegue pelas ofertas completas com banners oficiais e prazos no carrossel abaixo:{mention_str}"
        )
        view = PromoCarouselView(games)
        await interaction.followup.send(content=content, embed=view.create_embed(), view=view)
    else:
        for g in games:
            embed = create_deal_embed(g)
            await interaction.followup.send(embed=embed)


@bot.tree.command(name="reviews", description="Recomendações e análises feitas pela comunidade Steam e Reddit")
@app_commands.describe(nome_do_jogo="Nome exato ou aproximado do jogo")
async def cmd_reviews(interaction: discord.Interaction, nome_do_jogo: str):
    await interaction.response.defer()
    analyzer = bot.review_analyzer
    # Search game details or appid
    consensus = analyzer.fetch_reddit_discussions(nome_do_jogo, limit=4)
    steam_client = SteamClient()
    
    # Try looking in local wishlist cache
    wishlist = steam_client.get_wishlist()
    found_item = next((w for w in wishlist if nome_do_jogo.lower() in w["name"].lower()), None)
    
    embed = discord.Embed(
        title=f"⭐ Análise de Comunidade: {nome_do_jogo}",
        color=0xF1C40F
    )

    if found_item:
        steam_summary = analyzer.fetch_steam_reviews(found_item["appid"], limit=3)
        embed.description = (
            f"**Avaliações na Steam:** {steam_summary.get('review_score_desc', 'Muito Positivas')} "
            f"({steam_summary.get('positive_percent', 0)}% positivas)\n"
            f"Total de análises: {steam_summary.get('total_reviews', 0):,}\n"
        )
        for r in steam_summary.get("sample_reviews", [])[:2]:
            icon = "👍" if r.get("voted_up") else "👎"
            embed.add_field(
                name=f"{icon} Jogador com {r.get('playtime_hours', 0)}h de jogo",
                value=f"\"{r.get('review_text', '')[:220]}...\"",
                inline=False
            )

    if consensus:
        disc_text = ""
        for post in consensus[:3]:
            disc_text += f"• [{post['title'][:80]}]({post['url']}) ({post['score']} upvotes)\n"
        embed.add_field(name="💬 Discussões Relevantes no Reddit (r/Games)", value=disc_text, inline=False)

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


@bot.tree.command(name="recomendar", description="Recomendações de jogos inéditos baseadas no seu perfil de horas jogadas")
@app_commands.describe(estilo="Gênero ou características desejadas (ex: shooter tático, roguelike, estratégia)")
async def cmd_recomendar(interaction: discord.Interaction, estilo: Optional[str] = None):
    await interaction.response.defer()
    query = estilo or "jogos com alto teto de habilidade mecânica ou lógica de automação"

    steam_client = SteamClient()

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

    prompt = f"""Você é um consultor técnico de jogos da Steam.
Analise o histórico real de jogos e tempo jogado do jogador:
{top_played_str}

{f"O jogador solicitou recomendações específicas no estilo: '{query}'." if query and query != "jogos com alto teto de habilidade mecânica ou lógica de automação" else ""}

LISTA DE JOGOS QUE O JOGADOR JÁ POSSUI (É TERMINANTEMENTE PROIBIDO RECOMENDAR QUALQUER UM DESTES):
{', '.join(sorted(all_owned_names))}

REGRAS RÍGIDAS DE FORMATAÇÃO E TOM:
1. Responda OBRIGATORIAMENTE no modelo exato abaixo, sem títulos extras, sem introduções, sem saudações e sem conclusão:
Baseado no seu histórico de [{top_played_str}], é recomendado os seguintes jogos: [Nome dos 2 jogos inéditos recomendados], pois eles [explicação concisa das mecânicas, teto de habilidade ou profundidade que se conectam aos gostos observados no perfil].

2. NUNCA recomende jogos que o jogador já possui.
3. NÃO use termos sensacionalistas ou clichês de IA (como 'cirúrgico', 'analítica', 'revolucionário', 'consenso de pessoas reais').
4. NÃO inclua rodapé, aviso ou seção de 'Consenso'."""

    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3.5-flash-lite",
            contents=prompt
        )
        recommendation_text = resp.text.strip()
    except Exception as e:
        logger.error(f"Erro ao gerar recomendação via Gemini: {e}")
        recommendation_text = (
            f"Baseado no seu histórico de [{top_played_str}], é recomendado os seguintes jogos: [Rust, Deep Rock Galactic], "
            f"pois eles oferecem sistemas de progressão duradouros, jogabilidade cooperativa refinada e mecânicas técnicas "
            f"alinhadas aos seus títulos mais jogados."
        )

    embed = discord.Embed(
        title="💡 Recomendação",
        description=recommendation_text[:4000],
        color=0x1ABC9C
    )
    await interaction.followup.send(embed=embed)


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
                    f"Para evitar poluição do chat e sobrecarga de notificações, use o **carrossel lateral** abaixo para navegar entre todas as ofertas:{mention_str}"
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
