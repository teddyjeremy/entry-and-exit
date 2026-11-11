import unittest

from strategy.portfolio_rules import (
    evaluate_entry_capacity,
    maximum_concurrent_positions,
    trade_stake_usd,
)


class PortfolioRulesTests(unittest.TestCase):
    def test_one_slot_below_first_five_dollar_milestone(self):
        self.assertEqual(maximum_concurrent_positions(2.70), 1)
        self.assertEqual(maximum_concurrent_positions(4.99), 1)

    def test_two_slots_at_five_dollars(self):
        self.assertEqual(maximum_concurrent_positions(5.00), 2)
        self.assertEqual(maximum_concurrent_positions(9.99), 2)

    def test_three_slots_at_ten_dollars(self):
        self.assertEqual(maximum_concurrent_positions(10.00), 3)

    def test_capacity_increases_one_per_five_dollar_milestone(self):
        self.assertEqual(maximum_concurrent_positions(15.00), 4)
        self.assertEqual(maximum_concurrent_positions(20.00), 5)

    def test_waits_for_existing_position_to_exit_before_reusing_slot(self):
        result = evaluate_entry_capacity(
            "new-mint", 2.70, ["open-mint"], ["open-mint"]
        )
        self.assertFalse(result["approved"])
        self.assertEqual(result["available_slots"], 0)
        self.assertIn("maximum_concurrent_positions_reached", result["rejection_reasons"])

    def test_exit_releases_slot_for_a_different_coin(self):
        result = evaluate_entry_capacity(
            "new-mint", 2.70, [], ["previously-traded-mint"]
        )
        self.assertTrue(result["approved"])
        self.assertEqual(result["available_slots"], 1)

    def test_never_reenters_a_coin_that_was_already_traded(self):
        result = evaluate_entry_capacity(
            "same-mint", 10.00, ["other-a", "other-b"], ["same-mint", "other-a", "other-b"]
        )
        self.assertFalse(result["approved"])
        self.assertIn("coin_already_traded", result["rejection_reasons"])

    def test_open_coin_is_rejected_even_if_trade_history_was_not_passed(self):
        result = evaluate_entry_capacity(
            "open-mint", 10.00, ["open-mint"], []
        )
        self.assertFalse(result["approved"])
        self.assertIn("coin_already_traded", result["rejection_reasons"])

    def test_allows_second_position_only_after_equity_reaches_five(self):
        below = evaluate_entry_capacity("new-b", 4.99, ["open-a"], ["open-a"])
        reached = evaluate_entry_capacity("new-b", 5.00, ["open-a"], ["open-a"])
        self.assertFalse(below["approved"])
        self.assertTrue(reached["approved"])
        self.assertEqual(reached["available_slots"], 1)

    def test_invalid_portfolio_fails_closed(self):
        result = evaluate_entry_capacity("mint", float("nan"), [], [])
        self.assertFalse(result["approved"])
        self.assertIn("invalid_portfolio_or_position_state", result["rejection_reasons"])

    def test_duplicate_open_position_state_fails_closed(self):
        result = evaluate_entry_capacity("new-mint", 10, ["a", "a"], ["a"])
        self.assertFalse(result["approved"])
        self.assertIn("duplicate_open_position_state", result["rejection_reasons"])


class TradeStakeSizingTests(unittest.TestCase):
    def test_initial_stake_and_first_doubling(self):
        self.assertEqual(trade_stake_usd(2.70), 1.00)
        self.assertEqual(trade_stake_usd(5.39), 1.00)
        self.assertEqual(trade_stake_usd(5.40), 1.50)

    def test_each_full_doubling_increases_stake_by_fifty_percent(self):
        self.assertEqual(trade_stake_usd(10.80), 2.25)
        self.assertEqual(trade_stake_usd(21.60), 3.38)
        self.assertEqual(trade_stake_usd(43.20), 5.06)

    def test_does_not_increase_before_a_full_doubling(self):
        self.assertEqual(trade_stake_usd(10.79), 1.50)
        self.assertEqual(trade_stake_usd(20.00), 2.25)

    def test_stake_never_exceeds_available_equity_or_cap(self):
        self.assertEqual(trade_stake_usd(0), 0.00)
        self.assertEqual(trade_stake_usd(0.50), 0.50)
        self.assertEqual(
            trade_stake_usd(100_000, maximum_stake_usd=100), 100.00
        )

    def test_custom_starting_portfolio_and_stake(self):
        self.assertEqual(
            trade_stake_usd(
                20, starting_portfolio_usd=10, starting_stake_usd=2
            ),
            3.00,
        )

    def test_invalid_stake_configuration_is_rejected(self):
        for value in (-1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    trade_stake_usd(value)
        with self.assertRaises(ValueError):
            trade_stake_usd(10, growth_per_doubling=0.9)


if __name__ == "__main__":
    unittest.main()
