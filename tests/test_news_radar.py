"""Unit tests for News Radar taste relevance scoring."""

import unittest
from tools.news_radar import NewsRadar


class TestNewsRadar(unittest.TestCase):
    def setUp(self):
        self.radar = NewsRadar()

    def test_high_skill_shooter_scores_high(self):
        score, cats = self.radar.score_relevance(
            title="New Tactical Shooter Announces Competitive Esports Tournaments",
            summary="Focus on aim, reflex, movement mechanics and precision gunplay."
        )
        self.assertGreaterEqual(score, 6)
        self.assertIn("tactical_and_precision", cats)

    def test_automation_logic_game_scores_high(self):
        score, cats = self.radar.score_relevance(
            title="Indie Automation Puzzle Game Features In-Game Scripting Language",
            summary="Players use logic and programming to build sprawling factory systems."
        )
        self.assertGreaterEqual(score, 6)
        self.assertIn("automation_and_logic", cats)

    def test_unrelated_news_scores_zero(self):
        score, cats = self.radar.score_relevance(
            title="Cozy Animal Farming Simulation Releases Cozy Tea Party DLC",
            summary="Relax and decorate your garden with cute plants."
        )
        self.assertEqual(score, 0)
        self.assertEqual(len(cats), 0)


if __name__ == "__main__":
    unittest.main()
