"""Unit tests for Reaction Panel emoji mapping, 12 Steam tags, split messages, and active alerts."""

import unittest
from tools.preference_manager import (
    PreferenceManager,
    TAG_EMOJI_MAP,
    PRICE_EMOJI_MAP,
    AVAILABLE_TAGS
)


class TestReactionPanel(unittest.TestCase):
    def setUp(self):
        self.mgr = PreferenceManager()
        self.user_id = 999111

    def test_all_12_required_steam_tags_exist(self):
        required_tags = [
            "indie", "rpg", "strategy", "puzzle", "pvp", "horror",
            "action", "adventure", "survival", "roguelike", "management", "tower_defense"
        ]
        self.assertEqual(len(TAG_EMOJI_MAP), 12, "Must have exactly 12 tag emojis")
        for tag in required_tags:
            self.assertIn(tag, AVAILABLE_TAGS, f"Required tag {tag} must be in AVAILABLE_TAGS")

        for emoji, tag in TAG_EMOJI_MAP.items():
            self.assertIn(tag, AVAILABLE_TAGS, f"Tag {tag} mapped to emoji {emoji} must be valid")

    def test_price_emoji_mapping(self):
        self.assertEqual(len(PRICE_EMOJI_MAP), 5, "Must have 5 price tier emojis")
        for emoji, price in PRICE_EMOJI_MAP.items():
            self.assertGreater(price, 0, f"Price for {emoji} must be positive")

    def test_add_and_remove_tag_via_reaction(self):
        # User reacts with 💎 (indie)
        self.mgr.add_user_tag(self.user_id, TAG_EMOJI_MAP["💎"])
        pref = self.mgr.get_user_preference(self.user_id)
        self.assertIn("indie", pref["tags"])

        # User reacts with 🏰 (tower_defense)
        self.mgr.add_user_tag(self.user_id, TAG_EMOJI_MAP["🏰"])
        pref = self.mgr.get_user_preference(self.user_id)
        self.assertIn("tower_defense", pref["tags"])

        # User removes 💎 (indie)
        self.mgr.remove_user_tag(self.user_id, TAG_EMOJI_MAP["💎"])
        pref = self.mgr.get_user_preference(self.user_id)
        self.assertNotIn("indie", pref["tags"])
        self.assertIn("tower_defense", pref["tags"])

    def test_panel_split_messages_persistence(self):
        guild_id = 777111
        cat_id = 12345678
        budget_id = 87654321
        self.mgr.set_panel_messages(guild_id, cat_id, budget_id)
        msgs = self.mgr.get_panel_messages(guild_id)
        self.assertEqual(msgs["category_message_id"], cat_id)
        self.assertEqual(msgs["budget_message_id"], budget_id)

    def test_active_alerts_tracking_and_removal(self):
        test_alert = {
            "message_id": 998877,
            "channel_id": 112233,
            "guild_id": 445566,
            "appid": 108600,
            "name": "Project Zomboid",
            "posted_at": "2026-09-03T18:00:00"
        }
        self.mgr.save_active_alert(test_alert)
        alerts = self.mgr.get_active_alerts()
        found = any(a.get("message_id") == 998877 for a in alerts)
        self.assertTrue(found, "Saved active alert should be in active_alerts list")

        self.mgr.remove_active_alert(998877)
        alerts_after = self.mgr.get_active_alerts()
        found_after = any(a.get("message_id") == 998877 for a in alerts_after)
        self.assertFalse(found_after, "Removed active alert should no longer exist")


if __name__ == "__main__":
    unittest.main()
