"""Conservative extraction of per-trader token and quote-balance evidence.

This module reports observed balance deltas. It deliberately does not turn
those deltas into a trade price, volume, fees, or P&L.
"""
from __future__ import annotations

from strategy.helius_parser import NATIVE_SOL_MINT


class AmountEvidenceError(ValueError):
    """Raised when balance evidence is malformed or cannot be interpreted."""


def _native_delta(account_data: list, address: str):
    found = False
    total = 0
    for item in account_data:
        if not isinstance(item, dict) or item.get("account") != address:
            continue
        value = item.get("nativeBalanceChange")
        if isinstance(value, bool) or not isinstance(value, int):
            raise AmountEvidenceError("nativeBalanceChange must be an integer")
        found = True
        total += value
    return total if found else None


def _token_delta(account_data: list, mint: str, owner: str):
    found = False
    total = 0
    decimals = None
    for item in account_data:
        if not isinstance(item, dict):
            continue
        changes = item.get("tokenBalanceChanges", [])
        if not isinstance(changes, list):
            raise AmountEvidenceError("tokenBalanceChanges must be a list")
        for change in changes:
            if not isinstance(change, dict) or change.get("mint") != mint or change.get("userAccount") != owner:
                continue
            raw = change.get("rawTokenAmount")
            if not isinstance(raw, dict):
                raise AmountEvidenceError("rawTokenAmount is missing")
            amount = raw.get("tokenAmount")
            try:
                amount = int(amount)
            except (TypeError, ValueError) as exc:
                raise AmountEvidenceError("raw token amount must be an integer string") from exc
            scale = raw.get("decimals")
            if isinstance(scale, bool) or not isinstance(scale, int) or scale < 0:
                raise AmountEvidenceError("token decimals must be a non-negative integer")
            if decimals is not None and decimals != scale:
                raise AmountEvidenceError("conflicting token decimals in one transaction")
            decimals = scale
            total += amount
            found = True
    return (total, decimals) if found else (None, None)


def _native_transfer_sum(transfers, sender: str, receiver: str):
    if not isinstance(transfers, list):
        return None
    total = 0
    found = False
    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue
        if transfer.get("fromUserAccount") != sender or transfer.get("toUserAccount") != receiver:
            continue
        amount = transfer.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise AmountEvidenceError("native transfer amount must be an integer")
        total += amount
        found = True
    return total if found else 0


def reconcile_trade_balance_evidence(transaction: dict, event: dict) -> dict:
    """Reconcile user/curve base-token deltas and expose quote-balance evidence.

    The event must come from parse_pump_fun_evidence, so user/mint/curve/quote
    roles are tied to the pinned Pump IDL account positions.
    """
    if not isinstance(transaction, dict) or not isinstance(event, dict):
        raise AmountEvidenceError("transaction and event must be objects")
    signature = transaction.get("signature")
    if not isinstance(signature, str) or not signature:
        raise AmountEvidenceError("transaction signature is required")
    if transaction.get("transactionError") is not None:
        return {"signature": signature, "status": "failed_transaction"}
    for key in ("side", "mint", "bonding_curve", "user", "quote_mint"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise AmountEvidenceError(f"event {key} is required")
    if event["side"] not in ("buy", "sell"):
        raise AmountEvidenceError("event side must be buy or sell")

    account_data = transaction.get("accountData")
    if not isinstance(account_data, list):
        return {"signature": signature, "status": "missing_account_data"}

    user_delta, user_decimals = _token_delta(account_data, event["mint"], event["user"])
    curve_delta, curve_decimals = _token_delta(account_data, event["mint"], event["bonding_curve"])
    if user_delta is None or curve_delta is None:
        return {
            "signature": signature,
            "status": "missing_base_token_balance_evidence",
            "trader_base_token_delta_raw": user_delta,
            "curve_base_token_delta_raw": curve_delta,
        }

    direction_valid = (
        user_delta > 0 and curve_delta < 0
        if event["side"] == "buy"
        else user_delta < 0 and curve_delta > 0
    )
    decimals_match = user_decimals == curve_decimals
    token_balances_reconcile = direction_valid and decimals_match and user_delta == -curve_delta

    result = {
        "signature": signature,
        "status": "reconciled_token_balances" if token_balances_reconcile else "token_balance_mismatch",
        "side": event["side"],
        "instruction": event.get("instruction"),
        "mint": event["mint"],
        "bonding_curve": event["bonding_curve"],
        "trader": event["user"],
        "trader_base_token_delta_raw": user_delta,
        "curve_base_token_delta_raw": curve_delta,
        "base_token_decimals": user_decimals,
        "actual_base_token_amount_raw": abs(user_delta) if direction_valid else None,
        "base_token_balances_reconcile": token_balances_reconcile,
    }

    if event["quote_mint"] == NATIVE_SOL_MINT:
        native_sum = 0
        native_sum_valid = True
        for item in account_data:
            if not isinstance(item, dict):
                native_sum_valid = False
                continue
            value = item.get("nativeBalanceChange", 0)
            if isinstance(value, bool) or not isinstance(value, int):
                native_sum_valid = False
            else:
                native_sum += value
        fee = transaction.get("fee")
        fee_valid = isinstance(fee, int) and not isinstance(fee, bool) and fee >= 0
        result["quote_balance_evidence"] = {
            "asset": "native_SOL",
            "trader_native_balance_change_lamports": _native_delta(account_data, event["user"]),
            "curve_native_balance_change_lamports": _native_delta(account_data, event["bonding_curve"]),
            "trader_to_curve_native_transfers_lamports": _native_transfer_sum(
                transaction.get("nativeTransfers"), event["user"], event["bonding_curve"]
            ),
            "curve_to_trader_native_transfers_lamports": _native_transfer_sum(
                transaction.get("nativeTransfers"), event["bonding_curve"], event["user"]
            ),
            "network_fee_lamports": fee if fee_valid else None,
            "all_native_balance_changes_reconcile_to_network_fee": (
                native_sum_valid and fee_valid and native_sum == -fee
            ),
        }
    else:
        user_quote_delta, user_quote_decimals = _token_delta(
            account_data, event["quote_mint"], event["user"]
        )
        curve_quote_delta, curve_quote_decimals = _token_delta(
            account_data, event["quote_mint"], event["bonding_curve"]
        )
        result["quote_balance_evidence"] = {
            "asset": "quote_token",
            "quote_mint": event["quote_mint"],
            "trader_quote_token_delta_raw": user_quote_delta,
            "curve_quote_token_delta_raw": curve_quote_delta,
            "quote_token_decimals": user_quote_decimals,
            "quote_token_balances_reconcile": (
                user_quote_delta is not None
                and curve_quote_delta is not None
                and user_quote_decimals == curve_quote_decimals
                and user_quote_delta == -curve_quote_delta
            ),
        }

    return result
