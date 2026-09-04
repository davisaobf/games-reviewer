"""Unit tests for PromoCarouselView, deal embeds, and enriched Steam details."""

import unittest
from tools.steam_api import SteamClient
from agent.discord_bot import create_deal_embed, PromoCarouselView


class TestCarouselAndDetails(unittest.TestCase):
    def setUp(self):
        self.sample_games = [
            {
                "name": f"Game {i}",
                "appid": 1000 + i,
                "current_price": 19.99 + i,
                "historical_low": 19.99 + i,
                "discount_percent": 50,
                "promo_end": "Oferta válida até 10 de setembro",
                "store_url": f"https://store.steampowered.com/app/{1000 + i}/",
                "tags": ["Indie", "Action", "RPG"],
                "header_image": f"https://cdn.steam.com/header_{i}.jpg",
                "score_desc": "Extremamente Positivas",
                "pos_pct": 96
            }
            for i in range(6)
        ]

    def test_create_deal_embed_has_banner_and_tags(self):
        game = self.sample_games[0]
        embed = create_deal_embed(game, page_info="1/6")
        self.assertIn("Game 0", embed.title)
        self.assertIn("R$ 19.99", embed.description)
        self.assertIn("Indie, Action, RPG", embed.description)
        self.assertIn("Oferta válida até 10 de setembro", embed.description)
        self.assertEqual(embed.image.url, game["header_image"])

    def test_promo_carousel_view_navigation(self):
        view = PromoCarouselView(self.sample_games)
        # Initial page is 0
        self.assertEqual(view.current_page, 0)
        self.assertTrue(view.btn_prev.disabled, "Previous button must be disabled on first page")
        self.assertFalse(view.btn_next.disabled, "Next button must be enabled on first page")
        self.assertEqual(view.btn_counter.label, "🎮 1 de 6")

        # Advance to last page
        view.current_page = 5
        view._update_buttons()
        self.assertFalse(view.btn_prev.disabled, "Previous button must be enabled on last page")
        self.assertTrue(view.btn_next.disabled, "Next button must be disabled on last page")
        self.assertEqual(view.btn_counter.label, "🎮 6 de 6")

    def test_steam_client_get_game_details_tags(self):
        client = SteamClient()
        # Test Core Keeper (1621690)
        details = client.get_game_details(1621690)
        self.assertIsNotNone(details)
        self.assertTrue(len(details.get("tags", [])) > 0, "Game must have extracted tags")
        self.assertTrue(len(details.get("header_image", "")) > 0, "Game must have header image")

    def test_steam_client_get_discount_end_info(self):
        client = SteamClient()
        # Test Core Keeper (1621690)
        end_info = client.get_discount_end_info(1621690)
        self.assertIn("text", end_info)
        self.assertTrue(len(end_info["text"]) > 0)


if __name__ == "__main__":
    unittest.main()
