"""Unit tests for PromoCarouselView, deal embeds, and enriched Steam details."""

import unittest
from tools.steam_api import SteamClient
from agent.discord_bot import create_deal_embed, PromoCarouselView, RecommendationCarouselView


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

    def test_recommendation_carousel_view(self):
        sample_recs = [
            {
                "name": "Risk of Rain 2",
                "appid": 632360,
                "price_txt": "R$ 59.99",
                "discount_percent": 0,
                "store_url": "https://store.steampowered.com/app/632360/",
                "header_image": "https://cdn.steam.com/header_ror2.jpg",
                "reason": "Ação em terceira pessoa bem fluida."
            },
            {
                "name": "Dead Cells",
                "appid": 588650,
                "price_txt": "R$ 47.49",
                "discount_percent": 20,
                "store_url": "https://store.steampowered.com/app/588650/",
                "header_image": "https://cdn.steam.com/header_dc.jpg",
                "reason": "Combate rápido e viciante."
            }
        ]
        view = RecommendationCarouselView(sample_recs)
        self.assertEqual(view.current_page, 0)
        self.assertTrue(view.btn_prev.disabled)
        self.assertFalse(view.btn_next.disabled)
        self.assertEqual(view.btn_counter.label, "🎮 1 de 2")

        embed = view.create_embed()
        self.assertIn("Risk of Rain 2", embed.title)
        self.assertIn("Ação em terceira pessoa bem fluida.", embed.description)
        self.assertIn("R$ 59.99", embed.description)

        # Go to page 2
        view.current_page = 1
        view._update_buttons()
        self.assertFalse(view.btn_prev.disabled)
        self.assertTrue(view.btn_next.disabled)
        self.assertEqual(view.btn_counter.label, "🎮 2 de 2")

    def test_deal_and_recommendation_titles_and_objective_status(self):
        # Case 1: Standard deal at historical low
        deal_game = {
            "name": "Hollow Knight",
            "appid": 367520,
            "current_price": 23.49,
            "historical_low": 23.49,
            "discount_percent": 50,
            "is_recommendation": False
        }
        embed = create_deal_embed(deal_game, page_info="1/3")
        self.assertEqual(embed.title, "Hollow Knight (1/3)")
        self.assertNotIn("MENOR PREÇO", embed.title)
        self.assertNotIn("HISTÓRICO", embed.title)
        self.assertIn("📉 **Menor Preço Histórico:** Sim", embed.description)

        # Case 2: Standard deal NOT at historical low
        deal_not_lowest = {
            "name": "Celeste",
            "appid": 504230,
            "current_price": 29.99,
            "historical_low": 14.99,
            "discount_percent": 25,
            "is_recommendation": False
        }
        embed_not_low = create_deal_embed(deal_not_lowest)
        self.assertEqual(embed_not_low.title, "Celeste")
        self.assertIn("📉 **Menor Preço Histórico:** Não (Menor: R$ 14.99)", embed_not_low.description)

        # Case 3: Community recommendation deal
        rec_game = {
            "name": "Dead Cells",
            "appid": 588650,
            "current_price": 47.49,
            "historical_low": 47.49,
            "discount_percent": 20,
            "is_recommendation": True
        }
        embed_rec = create_deal_embed(rec_game, page_info="2/3")
        self.assertEqual(embed_rec.title, "Recomendação (2/3): Dead Cells")
        self.assertNotIn("HISTÓRICA", embed_rec.title.upper())
        self.assertNotIn("NOVA", embed_rec.title.upper())


if __name__ == "__main__":
    unittest.main()

