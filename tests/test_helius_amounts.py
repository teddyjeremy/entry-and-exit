import json
import unittest
from pathlib import Path

from strategy.helius_amounts import reconcile_trade_balance_evidence
from strategy.helius_parser import parse_pump_fun_evidence

MINT = "BXwgus8w5NPgxxWxTUUHiKUz3Jezn8RB6uqowcJxpump"
CURVE = "AzoTQt6G3J6J1i1dGXHuAmiVgGN9r58PUmuKbYRAfrhK"


class HeliusAmountEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).parent / "fixtures"
        cls.instruction_fixtures = {
            x["name"]: x for x in json.loads(
                (root / "trencher_pump_instructions.json").read_text(encoding="utf-8")
            )
        }
        cls.amount_fixtures = json.loads(
            (root / "trencher_amount_samples.json").read_text(encoding="utf-8")
        )

    def parse_event(self, sample):
        instruction = self.instruction_fixtures[sample["instruction_name"]]
        tx = {
            "signature": sample["signature"],
            "transactionError": None,
            "instructions": [{
                "programId": instruction["programId"],
                "data": instruction["data"],
                "accounts": instruction["accounts"],
            }],
        }
        parsed = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(parsed["status"], "recognized_bonding_curve_swap")
        return parsed["events"][0]

    def test_reconciles_actual_buy_token_balances_and_exposes_quote_evidence(self):
        sample = self.amount_fixtures[0]
        event = self.parse_event(sample)
        tx = {
            "signature": sample["signature"],
            "transactionError": None,
            "fee": sample["fee"],
            "feePayer": sample["feePayer"],
            "accountData": sample["accountData"],
            "nativeTransfers": sample["nativeTransfers"],
        }
        result = reconcile_trade_balance_evidence(tx, event)
        self.assertEqual(result["status"], "reconciled_token_balances")
        self.assertEqual(result["actual_base_token_amount_raw"], 23836088739)
        self.assertEqual(result["base_token_decimals"], 6)
        quote = result["quote_balance_evidence"]
        self.assertEqual(quote["trader_to_curve_native_transfers_lamports"], 9900000)
        self.assertEqual(quote["curve_native_balance_change_lamports"], 9853556)
        self.assertEqual(quote["trader_native_balance_change_lamports"], -10205000)
        self.assertTrue(quote["all_native_balance_changes_reconcile_to_network_fee"])

    def test_reconciles_actual_sell_token_balances_and_keeps_quote_deltas_separate(self):
        sample = self.amount_fixtures[1]
        event = self.parse_event(sample)
        tx = {
            "signature": sample["signature"],
            "transactionError": None,
            "fee": sample["fee"],
            "feePayer": sample["feePayer"],
            "accountData": sample["accountData"],
            "nativeTransfers": sample["nativeTransfers"],
        }
        result = reconcile_trade_balance_evidence(tx, event)
        self.assertEqual(result["status"], "reconciled_token_balances")
        self.assertEqual(result["actual_base_token_amount_raw"], 447727370313)
        self.assertEqual(result["base_token_decimals"], 6)
        quote = result["quote_balance_evidence"]
        self.assertEqual(quote["curve_native_balance_change_lamports"], -181707219)
        self.assertEqual(quote["trader_native_balance_change_lamports"], 177879387)
        self.assertEqual(quote["curve_to_trader_native_transfers_lamports"], 0)
        self.assertTrue(quote["all_native_balance_changes_reconcile_to_network_fee"])

    def test_failed_transaction_never_returns_trade_amounts(self):
        result = reconcile_trade_balance_evidence(
            {"signature": "failed", "transactionError": {"InstructionError": [0, "Custom"]}},
            {"side": "buy", "mint": MINT, "bonding_curve": CURVE, "user": "trader", "quote_mint": "So11111111111111111111111111111111111111112"},
        )
        self.assertEqual(result["status"], "failed_transaction")
        self.assertNotIn("actual_base_token_amount_raw", result)

    def test_missing_account_data_fails_closed(self):
        result = reconcile_trade_balance_evidence(
            {"signature": "missing", "transactionError": None},
            {"side": "buy", "mint": MINT, "bonding_curve": CURVE, "user": "trader", "quote_mint": "So11111111111111111111111111111111111111112"},
        )
        self.assertEqual(result["status"], "missing_account_data")


if __name__ == "__main__":
    unittest.main()
