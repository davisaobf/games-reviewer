# Especificações de APIs e Contratos de Dados

Este documento detalha os contratos, endpoints e regras de rate limiting utilizados pelo **Steam Game Reviewer**.

---

## 1. Steam Web API & Storefront API

### Endpoints
- **ResolveVanityURL**:
  - `GET https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/?key={key}&vanityurl={vanity}`
- **GetOwnedGames**:
  - `GET https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={key}&steamid={steamid}&include_appinfo=1`
- **Wishlist Data**:
  - `GET https://store.steampowered.com/wishlist/id/{user_id}/wishlistdata/?p=0`
- **Store App Details**:
  - `GET https://store.steampowered.com/api/appdetails?appids={appid}&cc=br&l=brazilian`
- **User Reviews**:
  - `GET https://store.steampowered.com/appreviews/{appid}?json=1&language=brazilian,english&num_per_page=20`

### Rate Limiting & Boas Práticas
- Máximo recomendado de 1 requisição por segundo no storefront público (`store.steampowered.com`) para evitar HTTP 429.
- Cache local de wishlist e metadados de jogos em `data/cache/`.

---

## 2. IsThereAnyDeal (ITAD) API v2

### Endpoints
- **Lookup Game**:
  - `GET https://api.isthereanydeal.com/games/lookup/v1?key={key}&title={title}`
- **Historical Low**:
  - `GET https://api.isthereanydeal.com/games/history/v2?key={key}&id={game_id}&country=BR`

### Regra Estrita de Disparo
$$\text{Disparo} = (\text{current\_price} \le \text{historical\_low}) \land (\text{discount\_percent} > 0)$$
Se o preço atual for superior mesmo em R$ 0,01 ao menor preço histórico registrado, o processo morre silenciosamente.

---

## 3. Gaming News RSS Feeds
- `https://www.reddit.com/r/Games/.rss`
- `https://www.reddit.com/r/pcgaming/.rss`
- `https://www.pcgamer.com/rss/`
Filtro baseado em palavras-chave do perfil do usuário: precisão mecânica, teto tático e automação/lógica.
