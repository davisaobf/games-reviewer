# 🎮 Games Reviewer - Steam AI Assistant

Assistente analítico e autônomo de jogos de alto desempenho construído com o **Google Antigravity SDK**, projetado para monitorar o ecossistema Steam, lista de desejos, menor preço histórico em Reais (BRL) e novidades do mundo dos jogos com foco no perfil competitivo, de precisão mecânica e de automação lógica.

---

## 🚀 Funcionalidades Principais

1. **Leitura e Mapeamento de Perfil (Tool-First)**:
   - Consulta a biblioteca pública do usuário (`davii123`), tempo de jogo e títulos recentes (*Shape of Dreams*, *The Farmer Was Replaced*, *TBH: Task Bar Hero*, etc.).
   - Arquitetura estritamente orientada a ferramentas: busca no catálogo antes de recomendar qualquer jogo, eliminando o risco de alucinações.

2. **Sentinela de Menor Preço Histórico (ITAD em BRL)**:
   - Integração com **IsThereAnyDeal API v2** configurada para `country=BR` e `currency=BRL`.
   - **Filtro Lógico Estrito**: Dispara alertas apenas se `preco_atual <= menor_historico`. Se o jogo estiver mesmo R$ 0,01 acima do menor histórico, o processo encerra silenciosamente, poupando o usuário de notificações redundantes de promoções triviais.

3. **Validação por Consenso da Comunidade**:
   - Extrai avaliações reais de jogadores na loja Steam e discussões do Reddit (r/Games).
   - Recomendações proativas exigem selo **Extremamente Positivas** (≥ 90-95% de aprovação) e justificativa detalhada das mecânicas, teto de habilidade (skill ceiling) e otimização.

4. **Radar de Notícias RSS**:
   - Varredura de feeds de games (r/Games, r/pcgaming, PC Gamer) filtrados por pontuação de afinidade com o gosto do usuário (shooters táticos, e-sports de alta precisão, lógica e programação).

5. **Notificações Push via Discord Webhook**:
   - Envio de embeds visuais com link direto da loja, percentual de desconto, confirmação do menor preço histórico e resumo do consenso.

6. **Skill Reutilizável Padrão Antigravity (`steam-game-reviewer`)**:
   - Empacotada com scripts CLI modulares (`steam_cli.py`, `itad_cli.py`, `news_cli.py`), rate limiting com monotonic timer, retries exponenciais e redirecionamento para arquivos JSON.

---

## 📂 Estrutura do Projeto

```text
Games Reviewer/
├── .env.example                     # Template de variáveis e credenciais
├── pyproject.toml                   # Metadados e build
├── requirements.txt                 # Dependências Python
├── run.py                           # Ponto de entrada CLI (chat, daemon, check-now)
├── config.py                        # Gerenciador de configurações e credenciais
├── agent/
│   ├── __init__.py
│   ├── core_agent.py                # Agente Google Antigravity e registro de tools
│   ├── system_prompt.py             # Prompt com regras rígidas de raciocínio
│   └── triggers.py                  # Proactive triggers periódicos (a cada 3 dias)
├── tools/
│   ├── __init__.py
│   ├── steam_api.py                 # Cliente Steam Web API e Storefront
│   ├── itad_api.py                  # Cliente IsThereAnyDeal e filtro estrito de preço
│   ├── community_reviews.py         # Extrator de reviews da Steam e Reddit
│   ├── news_radar.py                # Agregador de feeds RSS com filtro semântico
│   └── notifier.py                  # Despachador de notificações para Discord
├── skills/
│   └── steam-game-reviewer/
│       ├── SKILL.md                 # Especificação da Skill Antigravity
│       ├── scripts/                 # Ferramentas CLI com argparse e --output
│       └── references/              # Documentação das APIs
├── tests/                           # Suíte de testes automatizados (11 testes)
└── data/                            # Diretório local de logs e cache
```

---

## 🛠️ Instalação e Configuração

### 1. Criar e Ativar Ambiente Virtual
```bash
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configurar Credenciais Seguras
Copie o template `.env.example` para `.env` ou cadastre suas chaves sem exibi-las no terminal:

```powershell
# Google Gemini API Key
py -3.13 -c "import getpass, pathlib; val = getpass.getpass('Enter GEMINI_API_KEY: '); open('.env', 'a').write(f'GEMINI_API_KEY={val}\n'); print('Saved.')"

# Steam Web API Key
py -3.13 -c "import getpass, pathlib; val = getpass.getpass('Enter STEAM_API_KEY: '); open('.env', 'a').write(f'STEAM_API_KEY={val}\n'); print('Saved.')"

# IsThereAnyDeal API Key
py -3.13 -c "import getpass, pathlib; val = getpass.getpass('Enter ITAD_API_KEY: '); open('.env', 'a').write(f'ITAD_API_KEY={val}\n'); print('Saved.')"

# Discord Webhook URL
py -3.13 -c "import getpass, pathlib; val = getpass.getpass('Enter DISCORD_WEBHOOK_URL: '); open('.env', 'a').write(f'DISCORD_WEBHOOK_URL={val}\n'); print('Saved.')"
```

---

## 💻 Como Usar

### 🤖 Iniciar o Bot Interativo do Discord
```bash
python run.py --mode discord
```
Principais comandos slash disponíveis no servidor:
* `/painel` — Publica o painel de configuração de preferências por reações (dividido em mensagens temáticas com 12 tags oficiais Steam e teto de orçamento).
* `/check` — Força varredura imediata de promoções no menor preço histórico com datas de término da oferta.
* `/definir_canal` — [Admin] Define o canal oficial onde o bot postará os anúncios e alertas com menções cirúrgicas.
* `/minha_wishlist` — Lista os jogos da lista de desejos cadastrada.
* `/vincular_steam <url>` — Conecta a lista de desejos ao radar comunitário do servidor.
* `/noticias` — Manchetes filtradas do radar gamer.
* `/help` — Guia geral interativo.

### 🛡️ Iniciar Monitoramento Autônomo Antigravity (a cada 3 dias)
```bash
python run.py --mode daemon
```

### 🔍 Executar Varredura Imediata CLI
```bash
python run.py --check-now
```

---

## 🧪 Executando os Testes Automatizados

```bash
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```
Todos os **19 testes automatizados** cobrem:
* Roteamento de reações do painel de 3 mensagens e 12 tags oficiais da Steam.
* Persistência de preferências, orçamentos e canais de anúncios.
* Auto-exclusão e rastreamento de promoções expiradas.
* Filtro lógico estrito de menor preço histórico (morte silenciosa para ofertas +R$ 0,01).
* Varredura do radar de notícias, APIs da Steam e saídas JSON das ferramentas CLI.
