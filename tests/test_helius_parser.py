import json
import unittest
from pathlib import Path

from strategy.helius_parser import (
    NATIVE_SOL_MINT,
    PUMP_PROGRAM_ID,
    PUMP_TRADE_ACCOUNT_LAYOUTS,
    SUPPORTED_SWAP_DISCRIMINATORS,
    parse_pump_fun_evidence,
)

MINT = "Mint111111111111111111111111111111111111111"
CURVE = "Curve1111111111111111111111111111111111111"
TRADER = "Trader111111111111111111111111111111111111"


def b58encode(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    zeros = len(raw) - len(raw.lstrip(b"\x00"))
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * zeros + (encoded or ("" if zeros else "1"))


def pump_instruction(discriminator, mint=MINT, curve=CURVE, accounts=None):
    raw_discriminator = bytes(discriminator)
    side, instruction_name = SUPPORTED_SWAP_DISCRIMINATORS[raw_discriminator]
    layout = PUMP_TRADE_ACCOUNT_LAYOUTS[instruction_name]
    if accounts is None:
        indexes = [layout["mint_index"], layout["curve_index"], layout["user_index"]]
        if layout["quote_mint_index"] is not None:
            indexes.append(layout["quote_mint_index"])
        accounts = [f"Account{i}" for i in range(max(indexes) + 1)]
        accounts[layout["mint_index"]] = mint
        accounts[layout["curve_index"]] = curve
        accounts[layout["user_index"]] = TRADER
        if layout["quote_mint_index"] is not None:
            accounts[layout["quote_mint_index"]] = NATIVE_SOL_MINT
    return {
        "programId": PUMP_PROGRAM_ID,
        "data": b58encode(raw_discriminator + b"\x00" * 16),
        "accounts": accounts,
    }


class HeliusParserTests(unittest.TestCase):
    def transaction(self, instructions, **overrides):
        value = {
            "signature": "signature-1",
            "source": "JUPITER",
            "type": "SWAP",
            "transactionError": None,
            "instructions": instructions,
        }
        value.update(overrides)
        return value

    def test_recognizes_direct_buy_instruction(self):
        tx = self.transaction([pump_instruction([184, 23, 238, 97, 103, 197, 211, 61])])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["status"], "recognized_bonding_curve_swap")
        self.assertEqual(result["events"][0]["side"], "buy")
        self.assertEqual(result["events"][0]["instruction"], "buyV2")
        self.assertEqual(result["events"][0]["user"], TRADER)

    def test_recognizes_nested_sell_inside_router_transaction(self):
        nested = pump_instruction([93, 246, 130, 60, 231, 233, 64, 178])
        tx = self.transaction([{
            "programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "data": "router-data",
            "accounts": [],
            "innerInstructions": [nested],
        }])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["events"][0]["side"], "sell")

    def test_recognizes_actual_trencher_idl_instruction_samples(self):
        fixture_path = Path(__file__).parent / "fixtures" / "trencher_pump_instructions.json"
        fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
        expected_names = {
            "buy": ("buy", "buy"),
            "sell": ("sell", "sell"),
            "buy_v2": ("buy", "buyV2"),
            "sell_v2": ("sell", "sellV2"),
            "buy_v3": ("buy", "buyV3"),
            "sell_v3": ("sell", "sellV3"),
            "buy_exact_sol_in": ("buy", "buyExactSolIn"),
            "buy_exact_quote_in_v2": ("buy", "buyExactQuoteInV2"),
            "buy_exact_quote_in_v3": ("buy", "buyExactQuoteInV3"),
        }
        self.assertEqual({item["name"] for item in fixtures}, set(expected_names))
        for item in fixtures:
            with self.subTest(instruction=item["name"]):
                tx = self.transaction(
                    [{
                        "programId": item["programId"],
                        "data": item["data"],
                        "accounts": item["accounts"],
                    }],
                    signature=item["signature"],
                    source=item["source"],
                    type=item["type"],
                )
                result = parse_pump_fun_evidence(tx, item["mint"], item["bonding_curve"])
                self.assertEqual(result["status"], "recognized_bonding_curve_swap")
                self.assertEqual(
                    (result["events"][0]["side"], result["events"][0]["instruction"]),
                    expected_names[item["name"]],
                )
                layout = PUMP_TRADE_ACCOUNT_LAYOUTS[item["name"] if item["name"] in PUMP_TRADE_ACCOUNT_LAYOUTS else expected_names[item["name"]][1]]
                self.assertEqual(result["events"][0]["user"], item["accounts"][layout["user_index"]])

    def test_requires_exact_idl_account_positions(self):
        ix = pump_instruction([184, 23, 238, 97, 103, 197, 211, 61])
        layout = PUMP_TRADE_ACCOUNT_LAYOUTS["buyV2"]
        ix["accounts"][0] = MINT  # Also place it at a wrong index.
        ix["accounts"][layout["mint_index"]] = "DifferentMint"
        self.assertIn(MINT, ix["accounts"])
        result = parse_pump_fun_evidence(self.transaction([ix]), MINT, CURVE)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["unknown_pump_instructions"], 1)

    def test_unknown_discriminator_fails_closed(self):
        tx = self.transaction([{
            "programId": PUMP_PROGRAM_ID,
            "data": b58encode(bytes([1, 110, 170, 139, 54, 133, 131, 79]) + b"\x00" * 16),
            "accounts": [MINT, CURVE],
        }])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["status"], "unclassified_pump_instruction")
        self.assertEqual(result["events"], [])

    def test_requires_configured_curve_in_idl_curve_position(self):
        tx = self.transaction([pump_instruction(
            [184, 23, 238, 97, 103, 197, 211, 61],
            curve="DifferentCurve",
        )])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["events"], [])

    def test_failed_transaction_is_not_a_swap(self):
        tx = self.transaction(
            [pump_instruction([184, 23, 238, 97, 103, 197, 211, 61])],
            transactionError={"InstructionError": [0, "Custom"]},
        )
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["status"], "failed_transaction")
        self.assertEqual(result["events"], [])

    def test_does_not_trust_helius_source_or_type(self):
        tx = self.transaction(
            [pump_instruction([184, 23, 238, 97, 103, 197, 211, 61])],
            source="SYSTEM_PROGRAM",
            type="TRANSFER",
        )
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["events"][0]["side"], "buy")

    def test_non_pump_transaction_is_not_a_swap(self):
        tx = self.transaction([{"programId": "11111111111111111111111111111111", "data": "abc", "accounts": []}])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["status"], "no_pump_instruction")
        self.assertEqual(result["events"], [])

    def test_signature_is_required(self):
        with self.assertRaises(ValueError):
            parse_pump_fun_evidence({"instructions": []}, MINT, CURVE)


if __name__ == "__main__":
    unittest.main()
