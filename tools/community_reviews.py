"""Community review fetcher and sentiment analyzer (Steam Reviews & Reddit consensus)."""

import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, Dict, Any, List

logger = logging.getLogger("GamesReviewer.CommunityReviews")


class CommunityReviewAnalyzer:
    """Fetches real community sentiment from Steam Store reviews and Reddit discussions."""

    STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
    REDDIT_SEARCH_URL = "https://www.reddit.com/r/Games/search.json"

    def __init__(self):
        self.last_request = 0.0

    def _rate_limit(self, delay: float = 1.0):
        elapsed = time.monotonic() - self.last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self.last_request = time.monotonic()

    def fetch_steam_reviews(self, appid: int, limit: int = 15) -> Dict[str, Any]:
        """Pulls authentic user reviews and score summary from Steam Store."""
        self._rate_limit(1.0)
        url = self.STEAM_REVIEWS_URL.format(appid=appid)
        params = {
            "json": 1,
            "language": "brazilian,english",
            "purchase_type": "all",
            "num_per_page": min(limit, 50),
            "filter": "recent"
        }
        full_url = f"{url}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                full_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json"
                }
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                if data.get("success") == 1:
                    summary = data.get("query_summary", {})
                    total_reviews = summary.get("total_reviews", 0)
                    total_pos = summary.get("total_positive", 0)
                    pos_ratio = (total_pos / total_reviews * 100) if total_reviews > 0 else 0

                    reviews_sample = []
                    for r in data.get("reviews", [])[:limit]:
                        reviews_sample.append({
                            "voted_up": r.get("voted_up"),
                            "playtime_hours": round(r.get("author", {}).get("playtime_forever", 0) / 60, 1),
                            "votes_up": r.get("votes_up"),
                            "review_text": r.get("review", "")[:300].strip()
                        })

                    return {
                        "review_score_desc": summary.get("review_score_desc", "Neutras"),
                        "positive_percent": round(pos_ratio, 1),
                        "total_reviews": total_reviews,
                        "sample_reviews": reviews_sample,
                        "is_overwhelmingly_positive": pos_ratio >= 95.0 and total_reviews >= 500
                    }
        except Exception as e:
            logger.warning(f"Erro ao buscar análises da Steam para appid {appid}: {e}")

        return {
            "review_score_desc": "Indisponível",
            "positive_percent": 0.0,
            "total_reviews": 0,
            "sample_reviews": [],
            "is_overwhelmingly_positive": False
        }

    def fetch_reddit_discussions(self, game_title: str, limit: int = 5) -> List[Dict[str, str]]:
        """Pulls community discussions and post titles from r/Games."""
        self._rate_limit(1.5)
        params = {
            "q": game_title,
            "restrict_sr": "on",
            "sort": "relevance",
            "t": "year",
            "limit": limit
        }
        url = f"{self.REDDIT_SEARCH_URL}?{urllib.parse.urlencode(params)}"

        discussions = []
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GamesReviewerAssistant/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                children = data.get("data", {}).get("children", [])
                for item in children[:limit]:
                    post = item.get("data", {})
                    discussions.append({
                        "title": post.get("title", ""),
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "url": f"https://reddit.com{post.get('permalink', '')}"
                    })
        except Exception as e:
            logger.warning(f"Reddit search indisponível para {game_title}: {e}")

        return discussions

    def summarize_game_consensus(self, appid: int, game_title: str) -> Dict[str, Any]:
        """Combines Steam reviews and Reddit buzz into an actionable summary."""
        steam_data = self.fetch_steam_reviews(appid)
        reddit_posts = self.fetch_reddit_discussions(game_title)

        positive_pct = steam_data.get("positive_percent", 0)
        score_desc = steam_data.get("review_score_desc", "")

        is_recommended_tier = (
            "Extremamente Positivas" in score_desc
            or "Overwhelmingly Positive" in score_desc
            or positive_pct >= 90.0
        )

        return {
            "game_title": game_title,
            "appid": appid,
            "score_desc": score_desc,
            "positive_percent": positive_pct,
            "total_reviews": steam_data.get("total_reviews", 0),
            "is_recommended_tier": is_recommended_tier,
            "sample_reviews": steam_data.get("sample_reviews", []),
            "reddit_discussions": reddit_posts
        }
