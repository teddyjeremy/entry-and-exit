import unittest

from strategy.helius_parser import PUMP_PROGRAM_ID, parse_pump_fun_evidence

MINT = "Mint111111111111111111111111111111111111111"
CURVE = "Curve1111111111111111111111111111111111111"


def b58encode(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    zeros = len(raw) - len(raw.lstrip(b"\\x00"))
    number = int.from_bytes(raw, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * zeros + (encoded or ("" if zeros else "1"))


def pump_instruction(discriminator, accounts=None):
    return {
        "programId": PUMP_PROGRAM_ID,
        "data": b58encode(bytes(discriminator) + b"\\x00" * 16),
        "accounts": accounts or [MINT, CURVE],
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

    def test_unknown_legacy_discriminator_fails_closed(self):
        tx = self.transaction([pump_instruction([1, 110, 170, 139, 54, 133, 131, 79])])
        result = parse_pump_fun_evidence(tx, MINT, CURVE)
        self.assertEqual(result["status"], "unclassified_pump_instruction")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["unknown_pump_instructions"], 1)

    def test_requires_configured_curve_in_same_instruction(self):
        tx = self.transaction([pump_instruction(
            [184, 23, 238, 97, 103, 197, 211, 61],
            accounts=[MINT, "DifferentCurve"],
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
