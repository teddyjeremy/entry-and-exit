"""Conservative Pump.fun bonding-curve instruction evidence parser.

This module does not infer swaps from Helius labels or wallet balance deltas.
It recognizes pinned Pump IDL trade instructions only when the configured mint
and bonding curve occupy the exact account positions defined by the IDL.
Unknown instructions remain unclassified.
"""
from __future__ import annotations

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
NATIVE_SOL_MINT = "So11111111111111111111111111111111111111112"

# Discriminators pinned to pump-fun/pump-public-docs:
# - legacy buy/sell and v2: commit cb188ce08b5069196eef1f3e4a0c43b70099793b
# - v3 and exact-input variants: commit 639b87fb45c3adeffa6f7c4a1bf0cb85e392bf22
# Source blob SHAs and account layouts are recorded in docs/PUMP_IDL_MANIFEST.json.
SUPPORTED_SWAP_DISCRIMINATORS = {
    bytes([102, 6, 61, 18, 1, 218, 235, 234]): ("buy", "buy"),
    bytes([51, 230, 133, 164, 1, 127, 131, 173]): ("sell", "sell"),
    bytes([184, 23, 238, 97, 103, 197, 211, 61]): ("buy", "buyV2"),
    bytes([93, 246, 130, 60, 231, 233, 64, 178]): ("sell", "sellV2"),
    bytes([7, 5, 29, 196, 245, 23, 101, 80]): ("buy", "buyV3"),
    bytes([28, 146, 222, 119, 38, 196, 105, 213]): ("sell", "sellV3"),
    bytes([56, 252, 116, 8, 158, 223, 205, 95]): ("buy", "buyExactSolIn"),
    bytes([194, 171, 28, 70, 104, 77, 91, 47]): ("buy", "buyExactQuoteInV2"),
    bytes([225, 247, 80, 30, 213, 179, 132, 136]): ("buy", "buyExactQuoteInV3"),
}

# Account indexes from the corresponding pinned IDL instruction definitions.
# Legacy/SOL-only instructions omit quote_mint_index and use native SOL.
PUMP_TRADE_ACCOUNT_LAYOUTS = {
    "buy": {"mint_index": 2, "curve_index": 3, "user_index": 6, "quote_mint_index": None},
    "sell": {"mint_index": 2, "curve_index": 3, "user_index": 6, "quote_mint_index": None},
    "buyV2": {"mint_index": 1, "curve_index": 10, "user_index": 13, "quote_mint_index": 2},
    "sellV2": {"mint_index": 1, "curve_index": 10, "user_index": 13, "quote_mint_index": 2},
    "buyV3": {"mint_index": 1, "curve_index": 5, "user_index": 8, "quote_mint_index": 2},
    "sellV3": {"mint_index": 1, "curve_index": 5, "user_index": 8, "quote_mint_index": 2},
    "buyExactSolIn": {"mint_index": 2, "curve_index": 3, "user_index": 6, "quote_mint_index": None},
    "buyExactQuoteInV2": {"mint_index": 1, "curve_index": 10, "user_index": 13, "quote_mint_index": 2},
    "buyExactQuoteInV3": {"mint_index": 1, "curve_index": 5, "user_index": 8, "quote_mint_index": 2},
}


class ParseError(ValueError):
    """Raised when required transaction evidence is malformed."""


def _base58_decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if not isinstance(value, str) or not value:
        raise ParseError("instruction data must be a non-empty base58 string")
    number = 0
    for char in value:
        try:
            digit = alphabet.index(char)
        except ValueError as exc:
            raise ParseError("instruction data contains invalid base58") from exc
        number = number * 58 + digit
    decoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeroes + decoded


def _walk_instructions(instructions):
    if not isinstance(instructions, list):
        return
    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        yield instruction
        nested = instruction.get("innerInstructions")
        if isinstance(nested, list):
            yield from _walk_instructions(nested)


def parse_pump_fun_evidence(transaction: dict, mint: str, bonding_curve: str) -> dict:
    """Return conservative instruction evidence; never estimate trade amounts."""
    if not isinstance(transaction, dict):
        raise ParseError("transaction must be an object")
    if not isinstance(mint, str) or not mint or not isinstance(bonding_curve, str) or not bonding_curve:
        raise ParseError("mint and bonding_curve are required")

    signature = transaction.get("signature")
    if not isinstance(signature, str) or not signature:
        raise ParseError("transaction signature is required")

    if transaction.get("transactionError") is not None:
        return {
            "signature": signature,
            "status": "failed_transaction",
            "events": [],
            "unknown_pump_instructions": 0,
        }

    events = []
    unknown = 0
    saw_pump_program = False
    for instruction in _walk_instructions(transaction.get("instructions", [])):
        if instruction.get("programId") != PUMP_PROGRAM_ID:
            continue
        saw_pump_program = True
        try:
            raw = _base58_decode(instruction.get("data"))
        except ParseError:
            continue
        discriminator = raw[:8]
        recognized = SUPPORTED_SWAP_DISCRIMINATORS.get(discriminator)
        if recognized is None:
            continue
        side, instruction_name = recognized
        layout = PUMP_TRADE_ACCOUNT_LAYOUTS[instruction_name]
        accounts = instruction.get("accounts")
        if not isinstance(accounts, list):
            unknown += 1
            continue
        required_indexes = [
            layout["mint_index"], layout["curve_index"], layout["user_index"]
        ]
        if layout["quote_mint_index"] is not None:
            required_indexes.append(layout["quote_mint_index"])
        if len(accounts) <= max(required_indexes):
            unknown += 1
            continue
        if accounts[layout["mint_index"]] != mint or accounts[layout["curve_index"]] != bonding_curve:
            # If both configured addresses are present but in different IDL roles,
            # treat the instruction as unclassified rather than a target swap.
            if mint in accounts and bonding_curve in accounts:
                unknown += 1
            continue
        user = accounts[layout["user_index"]]
        quote_mint = (
            accounts[layout["quote_mint_index"]]
            if layout["quote_mint_index"] is not None
            else NATIVE_SOL_MINT
        )
        if not isinstance(user, str) or not user or not isinstance(quote_mint, str) or not quote_mint:
            unknown += 1
            continue
        events.append({
            "side": side,
            "instruction": instruction_name,
            "discriminator_hex": discriminator.hex(),
            "mint": mint,
            "bonding_curve": bonding_curve,
            "user": user,
            "quote_mint": quote_mint,
        })

    if events:
        status = "recognized_bonding_curve_swap"
    elif saw_pump_program:
        status = "unclassified_pump_instruction"
    else:
        status = "no_pump_instruction"

    return {
        "signature": signature,
        "status": status,
        "events": events,
        "unknown_pump_instructions": unknown,
    }
