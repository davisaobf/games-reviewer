"""Unit tests for ITAD strict lowest price filtering logic in BRL."""

import unittest
from tools.itad_api import evaluate_price_alert, load_local_price_history, save_local_price_history


class TestITADPriceFilter(unittest.TestCase):
    def setUp(self):
        # Clean up any test keys before each test
        history = load_local_price_history()
        for appid in ["999901", "999902", "999903", "999904", "999999"]:
            history.pop(appid, None)
        save_local_price_history(history)

    def tearDown(self):
        # Clean up any test keys after each test
        history = load_local_price_history()
        for appid in ["999901", "999902", "999903", "999904", "999999"]:
            history.pop(appid, None)
        save_local_price_history(history)

    def test_strict_lowest_price_triggers_alert(self):
        """When current price is lower than historical low, alert must trigger."""
        res = evaluate_price_alert(
            game_title="Test Precision Shooter",
            current_price=20.00,
            discount_percent=50,
            appid=999901
        )
        # Assuming historical low starts at 25.00
        res_check = evaluate_price_alert(
            game_title="Test Precision Shooter",
            current_price=19.99,
            discount_percent=50,
            appid=999901
        )
        self.assertTrue(res_check["trigger_alert"])
        self.assertTrue(res_check["is_new_all_time_low"])

    def test_equal_to_historical_low_triggers_alert(self):
        """When current price matches historical low, alert must trigger."""
        # Prime record with 30.00
        evaluate_price_alert("Test Logic Puzzle", 30.00, 20, 999902)
        # Matches 30.00
        res = evaluate_price_alert("Test Logic Puzzle", 30.00, 20, 999902)
        self.assertTrue(res["trigger_alert"])

    def test_one_cent_above_historical_low_dies_silently(self):
        """If price is even R$ 0.01 above historical low, trigger_alert MUST BE FALSE."""
        # Prime record with 15.00 as lowest
        evaluate_price_alert("The Farmer Was Replaced", 15.00, 50, 999903)
        # Current price is 15.01 (one cent higher)
        res = evaluate_price_alert("The Farmer Was Replaced", 15.01, 49, 999903)
        self.assertFalse(res["trigger_alert"], "O processo deveria morrer silenciosamente quando o preço é R$ 0,01 maior.")

    def test_no_discount_does_not_trigger_alert(self):
        """If there is no active discount (discount_percent == 0), alert must not trigger."""
        res = evaluate_price_alert("Full Price Game", 100.00, 0, 999904)
        self.assertFalse(res["trigger_alert"])

    def test_cheapshark_rejects_subpar_discount(self):
        """Friends vs Friends at 38% discount must NOT trigger alert because historical low discount is 81%."""
        res = evaluate_price_alert("Friends vs Friends", 32.98, 38, appid=1785150)
        self.assertFalse(res["trigger_alert"], "38% de desconto em Friends vs Friends não deve disparar alerta de menor preço histórico.")
        self.assertLess(res["historical_low"], 32.98, "O menor preço histórico calculado deve ser menor que R$ 32,98.")

    def test_unverified_first_seen_does_not_trigger(self):
        """A game seen for the first time without external historical data must establish baseline without triggering alert."""
        res = evaluate_price_alert("Brand New Mystery Game", 50.00, 20, appid=999999)
        self.assertFalse(res["trigger_alert"], "Primeira leitura sem validação externa nunca deve disparar alerta de menor histórico.")


if __name__ == "__main__":
    unittest.main()
