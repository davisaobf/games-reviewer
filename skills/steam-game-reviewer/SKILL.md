---
name: steam-game-reviewer
description: >-
  Agente analítico e autônomo para o ecossistema Steam. Mapeia perfil de jogador, monitora wishlist, valida consenso da comunidade (Steam/Reddit), filtra notícias por afinidade mecânica e alerta sobre menor preço histórico (Lowest Price em BRL) via IsThereAnyDeal e Discord.
---

# Steam Game Reviewer

## Overview
Esta skill capacita o agente a atuar como um curador pessoal e sentinela de jogos no ecossistema Steam, integrando:
1. **Leitura da Steam**: perfil público (`davii123`), catálogo de jogos possuídos, tempo de jogo e lista de desejos.
2. **Motor de Menor Preço Histórico (ITAD)**: verificação estrita em Reais (`currency=BRL`, `country=BR`). Dispara alertas apenas se `current_price <= historical_low`.
3. **Consenso da Comunidade**: extração de sentimento real em reviews da Steam e discussões do Reddit (mecânicas, teto de habilidade, otimização e endgame).
4. **Radar de Notícias**: filtragem de manchetes em feeds RSS orientada ao perfil de precisão tática e lógica/automação do usuário.
5. **Notificações Push**: despacho de alertas formatados em embeds ricos para o Discord.

## Dependencies
- `google-antigravity`: Orquestração autônoma do agente e execução de triggers.
- `python-dotenv`: Gerenciamento seguro de credenciais em `.env`.
- `feedparser` ou `xml.etree`: Leitura de feeds RSS.
- `urllib` e `requests`: Conexão com endpoints de Steam, IsThereAnyDeal e Discord.

## Quick Start

### 1. Inspecionar Perfil e Wishlist
```bash
python skills/steam-game-reviewer/scripts/steam_cli.py wishlist --user davii123 --output data/cache/wishlist.json
```

### 2. Validar Menor Preço Histórico
```bash
python skills/steam-game-reviewer/scripts/itad_cli.py check-lowest --title "Shape of Dreams" --price 24.99 --discount 50 --output data/cache/price_check.json
```

### 3. Varrer Radar de Notícias Relevantes
```bash
python skills/steam-game-reviewer/scripts/news_cli.py radar --min-score 2 --limit 5 --output data/cache/news.json
```

## Utility Scripts (CLI Pattern)

### `steam_cli.py`
Subcomandos:
- `profile --user <name> --output <file.json>`: Recupera biblioteca e jogos recentes.
- `wishlist --user <name> --output <file.json>`: Extrai wishlist com preços em BRL.
- `game --appid <id> --output <file.json>`: Detalhes oficiais do jogo na loja Steam.
- `reviews --appid <id> [--title <str>] --output <file.json>`: Análise de avaliações e consenso.

### `itad_cli.py`
Subcomandos:
- `check-lowest --title <str> [--appid <id>] --price <float> --discount <int> --output <file.json>`: Aplica o filtro estrito de menor preço histórico.
- `history --title <str> --output <file.json>`: Histórico geral de preços em BRL.

### `news_cli.py`
Subcomandos:
- `radar [--min-score <int>] [--limit <int>] --output <file.json>`: Busca notícias em r/Games, r/pcgaming e PC Gamer alinhadas aos gostos do usuário.

## Workflow

### 1. Mapeamento de Perfil (Tool-First)
Antes de qualquer recomendação, o agente executa `steam_cli.py profile` e `steam_cli.py wishlist` para mapear os gêneros de preferência (ex: reflexos rápidos, jogos competitivos, programação e automação como *The Farmer Was Replaced*).

### 2. Varredura Periódica de Descontos (Autonomia a cada 3 dias)
O agente percorre os itens da Wishlist. Para cada título em promoção, executa `itad_cli.py check-lowest`.
- Se `current_price <= historical_low`: prossegue para envio do alerta no Discord com resumo do consenso.
- Se `current_price > historical_low`: o processo morre silenciosamente, evitando spam desnecessário.

### 3. Recomendação Ativa (Expansão da Wishlist)
Para recomendar jogos fora da wishlist:
- Obrigatório consultar `steam_cli.py reviews` e validar que as análises são **Extremamente Positivas** (≥ 90-95% positivas).
- Justificar a recomendação citando mecânicas concretas (teto de habilidade, fluidez de movimentação, profundidade de sistemas).

## Rate Limiting
- **Steam Store**: Delay de 1,0s entre requisições com retry exponencial em HTTP 429.
- **IsThereAnyDeal API**: Delay de 0,5s entre chamadas e cache local em `data/price_history.json`.

## Common Mistakes
1. **Notificar qualquer promoção**: Não faça isso! Notifique SOMENTE quando for menor preço histórico (`<= historical_low`).
2. **Alucinar nomes de jogos**: Sempre execute a busca no catálogo Steam antes de emitir a resposta.
3. **Moeda incorreta**: Preços devem sempre ser calculados e exibidos em **Reais (BRL / R$)**.
