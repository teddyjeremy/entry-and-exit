"""Conservative Pump.fun bonding-curve instruction evidence parser.

This module does not infer swaps from Helius labels or wallet balance deltas.
It only recognizes explicitly supported Pump program instructions whose own
account list contains both the configured mint and bonding-curve address.
Unknown/legacy discriminators remain unclassified.
"""
from __future__ import annotations

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Discriminators pinned from the pump-fun/pump-public-docs IDL.
# Expand only after reviewing the instruction name and account layout.
SUPPORTED_SWAP_DISCRIMINATORS = {
    bytes([184, 23, 238, 97, 103, 197, 211, 61]): ("buy", "buyV2"),
    bytes([93, 246, 130, 60, 231, 233, 64, 178]): ("sell", "sellV2"),
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
    return b"\\x00" * leading_zeroes + decoded


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
    """Return conservative instruction evidence; never estimate trade amounts.

    Helius source/type are intentionally ignored because routed Pump swaps can
    be labelled JUPITER/OKX and non-swap records can be labelled TRANSFER.
    """
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
        accounts = instruction.get("accounts")
        if not isinstance(accounts, list) or mint not in accounts or bonding_curve not in accounts:
            continue
        try:
            raw = _base58_decode(instruction.get("data"))
        except ParseError:
            unknown += 1
            continue
        discriminator = raw[:8]
        recognized = SUPPORTED_SWAP_DISCRIMINATORS.get(discriminator)
        if recognized is None:
            unknown += 1
            continue
        side, instruction_name = recognized
        events.append({
            "side": side,
            "instruction": instruction_name,
            "discriminator_hex": discriminator.hex(),
            "mint": mint,
            "bonding_curve": bonding_curve,
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
