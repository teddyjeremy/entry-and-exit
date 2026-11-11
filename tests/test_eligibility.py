import json
import unittest
from pathlib import Path

from strategy.eligibility import evaluate_eligibility


CONFIG = json.loads((Path(__file__).resolve().parents[1] / 'config' / 'strategy_baseline.json').read_text())


def valid_snapshot():
    return {
        'is_pump_fun_bonding_curve': True,
        'bonding_curve_active': True,
        'migrated': False,
        'market_state_known': True,
        'buy_quote_available': True,
        'sell_quote_available': True,
        'market_cap_usd': 5000,
        'real_bonding_curve_sol_reserves': 5,
        'volume_sol_30s': 5,
        'unique_buyers_30s': 15,
        'entry_price_impact_percent': 2,
        'exit_price_impact_percent': 2,
        'round_trip_cost_percent': 4,
        'rpc_data_age_seconds': 2,
        'signal_age_seconds': 2,
        'buy_quote_age_seconds': 2,
        'sell_quote_age_seconds': 2,
    }


class EligibilityTests(unittest.TestCase):
    def test_snapshot_at_all_thresholds_is_eligible(self):
        result = evaluate_eligibility(valid_snapshot(), CONFIG)
        self.assertTrue(result['approved'], result['rejection_reasons'])
        self.assertEqual(result['rejection_reasons'], [])

    def test_migrated_token_is_never_eligible(self):
        snapshot = valid_snapshot()
        snapshot['migrated'] = True
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('failed:migrated', result['rejection_reasons'])

    def test_non_pump_fun_curve_is_rejected(self):
        snapshot = valid_snapshot()
        snapshot['is_pump_fun_bonding_curve'] = False
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('failed:is_pump_fun_bonding_curve', result['rejection_reasons'])

    def test_unknown_market_state_is_rejected(self):
        snapshot = valid_snapshot()
        snapshot['market_state_known'] = False
        self.assertFalse(evaluate_eligibility(snapshot, CONFIG)['approved'])

    def test_missing_sell_quote_is_rejected(self):
        snapshot = valid_snapshot()
        snapshot['sell_quote_available'] = False
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('failed:sell_quote_available', result['rejection_reasons'])

    def test_stale_rpc_data_is_rejected(self):
        snapshot = valid_snapshot()
        snapshot['rpc_data_age_seconds'] = 2.01
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('above_maximum:rpc_data_age_seconds', result['rejection_reasons'])

    def test_missing_fields_fail_closed(self):
        snapshot = valid_snapshot()
        del snapshot['migrated']
        del snapshot['real_bonding_curve_sol_reserves']
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('missing_or_invalid:migrated', result['rejection_reasons'])
        self.assertIn('missing_or_invalid:real_bonding_curve_sol_reserves', result['rejection_reasons'])

    def test_low_volume_is_rejected(self):
        snapshot = valid_snapshot()
        snapshot['volume_sol_30s'] = 4.99
        result = evaluate_eligibility(snapshot, CONFIG)
        self.assertFalse(result['approved'])
        self.assertIn('below_minimum:volume_sol_30s', result['rejection_reasons'])


if __name__ == '__main__':
    unittest.main()
