"""Gaming News Radar & RSS Aggregator tailored to user taste profile."""

import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional, Tuple

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

logger = logging.getLogger("GamesReviewer.NewsRadar")

# Keywords reflecting the user's high-skill / programming taste profile
TASTE_KEYWORDS = {
    "tactical_and_precision": [
        "tactical", "shooter", "fps", "competitive", "esports", "aim", "reflex",
        "precision", "movement", "counter-strike", "cs2", "valorant", "ultrakill", "doom"
    ],
    "automation_and_logic": [
        "automation", "programming", "puzzle", "logic", "coding", "farmer was replaced",
        "factorio", "shapez", "satisfactory", "zachtronics", "turing", "blueprint", "script"
    ],
    "skill_ceiling_and_action": [
        "high skill ceiling", "shape of dreams", "roguelite", "roguelike", "combat depth",
        "soulslike", "boss fight", "parry", "mechanics"
    ],
    "major_events_and_awards": [
        "game awards", "the game awards", "summer game fest", "gamescom",
        "steam next fest", "steam sale", "golden joystick", "state of play",
        "nintendo direct", "xbox showcase", "reveal", "goty", "announcement",
        "game of the year", "trailer", "premiere"
    ]
}


class NewsRadar:
    """Monitors RSS gaming feeds and filters stories matching user taste."""

    DEFAULT_FEEDS = [
        {"name": "r/Games (Reddit)", "url": "https://www.reddit.com/r/Games/.rss"},
        {"name": "r/pcgaming (Reddit)", "url": "https://www.reddit.com/r/pcgaming/.rss"},
        {"name": "PC Gamer", "url": "https://www.pcgamer.com/rss/"}
    ]

    def __init__(self, feeds: Optional[List[Dict[str, str]]] = None):
        self.feeds = feeds or self.DEFAULT_FEEDS

    def _fetch_feed(self, url: str) -> List[Dict[str, Any]]:
        """Fetches and parses an RSS/Atom feed."""
        entries = []
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GamesReviewerAssistant/1.0"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                content = resp.read()

                if HAS_FEEDPARSER:
                    parsed = feedparser.parse(content)
                    for e in parsed.entries[:20]:
                        entries.append({
                            "title": e.get("title", ""),
                            "link": e.get("link", ""),
                            "summary": e.get("summary", "")[:250],
                            "published": e.get("published", "")
                        })
                else:
                    # Fallback XML parsing
                    root = ET.fromstring(content)
                    # Support standard RSS 2.0
                    for item in root.findall(".//item")[:20]:
                        title = item.findtext("title", "")
                        link = item.findtext("link", "")
                        desc = item.findtext("description", "")[:250]
                        entries.append({
                            "title": title,
                            "link": link,
                            "summary": desc,
                            "published": item.findtext("pubDate", "")
                        })
        except Exception as e:
            logger.warning(f"Erro ao carregar feed {url}: {e}")

        return entries

    def score_relevance(self, title: str, summary: str) -> Tuple[int, List[str]]:
        text = f"{title} {summary}".lower()
        score = 0
        matched_categories = []

        for category, keywords in TASTE_KEYWORDS.items():
            matches = [kw for kw in keywords if kw in text]
            if matches:
                score += len(matches) * 2
                matched_categories.append(category)

        return score, matched_categories

    def get_relevant_news(self, min_score: int = 2, max_items: int = 10) -> List[Dict[str, Any]]:
        """Scans all feeds and returns news matching user taste."""
        all_news = []

        for feed in self.feeds:
            entries = self._fetch_feed(feed["url"])
            for e in entries:
                score, categories = self.score_relevance(e["title"], e["summary"])
                if score >= min_score:
                    all_news.append({
                        "source": feed["name"],
                        "title": e["title"],
                        "link": e["link"],
                        "summary": e["summary"],
                        "relevance_score": score,
                        "matched_categories": categories
                    })

        # Sort by relevance score descending
        all_news.sort(key=lambda x: x["relevance_score"], reverse=True)
        return all_news[:max_items]

