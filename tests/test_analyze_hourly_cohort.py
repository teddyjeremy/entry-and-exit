import unittest

from analyze_hourly_cohort import decode_curve_state, decode_transaction


MINT = "Mint111111111111111111111111111111111111111"
CURVE = "Curve111111111111111111111111111111111111"
BUYER = "Buyer111111111111111111111111111111111111"
SELLER = "Seller1111111111111111111111111111111111"


def tx_template(wallet, token_delta, native_delta, source, destination, signature):
    return {
        "timestamp": 1005,
        "signature": signature,
        "fee": 5000,
        "feePayer": wallet,
        "type": "UNKNOWN",
        "transactionError": None,
        "accountData": [
            {"account": wallet, "nativeBalanceChange": native_delta,
             "tokenBalanceChanges": [{"mint": MINT, "userAccount": wallet,
                                      "rawTokenAmount": {"decimals": 6,
                                                         "tokenAmount": str(token_delta)}}]}
        ],
        "tokenTransfers": [{
            "mint": MINT, "fromUserAccount": source,
            "toUserAccount": destination, "tokenAmount": abs(token_delta) / 1_000_000,
        }],
    }


class DecodeTransactionTests(unittest.TestCase):
    def test_direct_curve_buy(self):
        tx = tx_template(BUYER, 2_000_000, -1_000_000_000, CURVE, BUYER, "buy")
        events, quality = decode_transaction(tx, MINT, CURVE, 1000, 4600)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["side"], "BUY")
        self.assertEqual(events[0]["wallet"], BUYER)
        self.assertEqual(events[0]["classification_method"], "direct_bonding_curve_transfer")
        self.assertTrue(quality["in_window"])

    def test_direct_curve_sell(self):
        tx = tx_template(SELLER, -3_000_000, 2_000_000_000, SELLER, CURVE, "sell")
        events, _ = decode_transaction(tx, MINT, CURVE, 1000, 4600)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["side"], "SELL")
        self.assertEqual(events[0]["wallet"], SELLER)

    def test_excludes_out_of_window_and_failed_transactions(self):
        tx = tx_template(BUYER, 2_000_000, -1_000_000_000, CURVE, BUYER, "late")
        tx["timestamp"] = 4601
        events, quality = decode_transaction(tx, MINT, CURVE, 1000, 4600)
        self.assertEqual(events, [])
        self.assertFalse(quality["in_window"])
        tx["timestamp"] = 1005
        tx["transactionError"] = {"InstructionError": [0, "Custom"]}
        events, quality = decode_transaction(tx, MINT, CURVE, 1000, 4600)
        self.assertEqual(events, [])
        self.assertTrue(quality["failed"])


    def test_curve_state_emits_only_relative_reserve_and_price_evidence(self):
        tx = {
            "timestamp": 1005, "signature": "curve-buy", "slot": 1,
            "transactionError": None,
            "accountData": [
                {"account": CURVE, "nativeBalanceChange": 1_000_000_000,
                 "tokenBalanceChanges": [
                     {"mint": MINT, "userAccount": CURVE,
                      "rawTokenAmount": {"decimals": 6, "tokenAmount": "-1000000"}}
                 ]}
            ],
            "tokenTransfers": [],
        }
        event = decode_curve_state(tx, MINT, CURVE, 1000, 4600)
        self.assertIsNotNone(event)
        self.assertEqual(event["curve_native_balance_delta_sol"], 1.0)
        self.assertEqual(event["curve_token_balance_delta"], -1.0)
        self.assertEqual(event["implied_curve_price_sol_per_token_estimate"], 1.0)
        self.assertIn("Relative reserve movement only", event["liquidity_interpretation"])


    def test_curve_state_ignores_unrelated_native_movements(self):
        tx = {
            "timestamp": 1005, "signature": "unrelated", "slot": 1,
            "transactionError": None,
            "accountData": [{"account": CURVE, "nativeBalanceChange": 1_000_000_000,
                             "tokenBalanceChanges": []}],
            "tokenTransfers": [],
        }
        self.assertIsNone(decode_curve_state(tx, MINT, CURVE, 1000, 4600))

    def test_ambiguous_flow_is_not_guessed(self):
        tx = tx_template(BUYER, 2_000_000, 0, "OtherSource", "OtherDestination", "unknown")
        events, quality = decode_transaction(tx, MINT, CURVE, 1000, 4600)
        self.assertEqual(events, [])
        self.assertEqual(quality["unclassified_wallet_flows"], 1)


if __name__ == "__main__":
    unittest.main()
