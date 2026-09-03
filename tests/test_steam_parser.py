"""Unit tests for Steam API Client configuration and vanity parsing."""

import unittest
from tools.steam_api import SteamClient


class TestSteamClient(unittest.TestCase):
    def test_client_initialization_defaults(self):
        client = SteamClient(user_id="davii123")
        self.assertEqual(client.user_id, "davii123")
        self.assertEqual(client.delay, 1.0)

    def test_resolve_numeric_steamid64(self):
        numeric_id = "76561198000000000"
        client = SteamClient(user_id=numeric_id)
        resolved = client.resolve_vanity_url(numeric_id)
        self.assertEqual(resolved, numeric_id)


if __name__ == "__main__":
    unittest.main()
