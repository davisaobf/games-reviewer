"""Unit tests for PreferenceManager matching logic and storage."""

import unittest
from tools.preference_manager import PreferenceManager


class TestPreferenceManager(unittest.TestCase):
    def setUp(self):
        self.mgr = PreferenceManager()
        # Mock user 1001: Likes roguelike, max price 30.0
        self.mgr.update_user_tags(1001, ["roguelike"])
        self.mgr.update_user_max_price(1001, 30.0)

        # Mock user 1002: Likes action, max price 20.0
        self.mgr.update_user_tags(1002, ["action"])
        self.mgr.update_user_max_price(1002, 20.0)

        # Mock user 1003: Likes management, max price 100.0
        self.mgr.update_user_tags(1003, ["management"])
        self.mgr.update_user_max_price(1003, 100.0)

    def test_matching_users_with_tag_and_budget(self):
        # Game: Shape of Dreams (Price: 24.99, Tags: ["Action Roguelike", "High Skill Ceiling"])
        matching = self.mgr.find_users_to_notify(["Action Roguelike", "High Skill Ceiling"], 24.99)
        self.assertIn(1001, matching, "User 1001 should match (likes roguelike and budget is 30.0)")
        self.assertNotIn(1002, matching, "User 1002 likes action, not roguelike")
        self.assertNotIn(1003, matching, "User 1003 likes management, not roguelike")

    def test_budget_exceeded_skips_user(self):
        # Game: Ultrakill (Price: 24.99, Tags: ["Action", "FPS"])
        # User 1002 likes action, but budget is 20.0 (price 24.99 is above budget)
        matching = self.mgr.find_users_to_notify(["Action", "FPS"], 24.99)
        self.assertNotIn(1002, matching, "User 1002 budget is 20.0, game is 24.99, should NOT be notified")

    def test_announcement_channel_save_and_retrieve(self):
        guild_id = 987654321
        channel_id = 123456789
        self.mgr.set_announcement_channel(guild_id, channel_id)
        retrieved = self.mgr.get_announcement_channel(guild_id)
        self.assertEqual(retrieved, channel_id)


if __name__ == "__main__":
    unittest.main()
