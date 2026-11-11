#!/usr/bin/env python3
"""Audit and decode the raw Pump.fun hourly cohort into conservative trade evidence.

This does not make BUY decisions. Native balance deltas are recorded as observed
wallet changes, not asserted trade notional: fees, rent, tips and other legs can
affect them. Trade side is inferred from signed token/native deltas or a direct
bonding-curve transfer. Ambiguous transfers are counted, never silently guessed.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DAY = os.environ.get("COHORT_DATE", "2026-11-10")
HOUR = int(os.environ.get("COHORT_HOUR_UTC", "0"))
COHORT_DIR = ROOT / "data" / "hourly" / DAY / f"{HOUR:02d}"
ANALYSIS_DIR = COHORT_DIR / "analysis"
LAMPORTS_PER_SOL = 1_000_000_000


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {"_parse_error": True, "_line": line_number}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def decode_transaction(tx: dict[str, Any], mint: str, curve: str,
                       launch_ts: int, cutoff_ts: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return per-wallet BUY/SELL evidence and transaction-level quality counters."""
    ts = tx.get("timestamp")
    quality = {"in_window": False, "failed": bool(tx.get("transactionError")),
               "target_mint_transfers": 0, "unclassified_wallet_flows": 0}
    if not isinstance(ts, (int, float)) or not launch_ts <= int(ts) <= cutoff_ts:
        return [], quality
    quality["in_window"] = True
    if tx.get("transactionError"):
        return [], quality

    native_lamports: dict[str, int] = defaultdict(int)
    token_delta: dict[str, float] = defaultdict(float)
    token_decimals: dict[str, int] = {}
    for account in tx.get("accountData") or []:
        owner_account = account.get("account")
        if owner_account:
            native_lamports[owner_account] += int(account.get("nativeBalanceChange") or 0)
        for change in account.get("tokenBalanceChanges") or []:
            if change.get("mint") != mint:
                continue
            raw = change.get("rawTokenAmount") or {}
            decimals = int(raw.get("decimals") or 0)
            amount = as_float(raw.get("tokenAmount"))
            owner = change.get("userAccount") or owner_account
            if owner:
                token_delta[owner] += amount / (10 ** decimals)
                token_decimals[owner] = decimals

    direct_side: dict[str, str] = {}
    transfer_delta: dict[str, float] = defaultdict(float)
    target_transfers = []
    for transfer in tx.get("tokenTransfers") or []:
        if transfer.get("mint") != mint:
            continue
        target_transfers.append(transfer)
        amount = as_float(transfer.get("tokenAmount"))
        source = transfer.get("fromUserAccount")
        destination = transfer.get("toUserAccount")
        if source:
            transfer_delta[source] -= amount
        if destination:
            transfer_delta[destination] += amount
        if source == curve and destination and destination != curve:
            direct_side[destination] = "BUY"
        elif destination == curve and source and source != curve:
            direct_side[source] = "SELL"

    quality["target_mint_transfers"] = len(target_transfers)
    if not token_delta:
        token_delta = transfer_delta

    wallet_events = []
    for wallet, delta in token_delta.items():
        if abs(delta) < 1e-12:
            continue
        native_delta = native_lamports.get(wallet, 0)
        method = None
        side = direct_side.get(wallet)
        if side:
            method = "direct_bonding_curve_transfer"
        elif delta > 0 and native_delta < 0:
            side, method = "signed_balance_deltas", "signed_balance_deltas"
        elif delta < 0 and native_delta > 0:
            side, method = "signed_balance_deltas", "signed_balance_deltas"
        else:
            quality["unclassified_wallet_flows"] += 1
            continue

        fee_sol = (as_float(tx.get("fee")) / LAMPORTS_PER_SOL
                   if wallet == tx.get("feePayer") else 0.0)
        wallet_events.append({
            "mint": mint,
            "timestamp": int(ts),
            "timestamp_utc": datetime.fromtimestamp(int(ts), timezone.utc).isoformat(),
            "signature": tx.get("signature"),
            "slot": tx.get("slot"),
            "tx_type": tx.get("type"),
            "wallet": wallet,
            "side": side,
            "token_amount": abs(delta),
            "token_delta_signed": delta,
            "wallet_native_delta_sol": native_delta / LAMPORTS_PER_SOL,
            "fee_sol_if_fee_payer": fee_sol,
            "fee_payer": tx.get("feePayer"),
            "classification_method": method,
            "native_delta_is_trade_notional": False,
        })
    return wallet_events, quality


def decode_curve_state(tx: dict[str, Any], mint: str, curve: str,
                      launch_ts: int, cutoff_ts: int) -> dict[str, Any] | None:
    ts = tx.get("timestamp")
    if not isinstance(ts, (int, float)) or not launch_ts <= int(ts) <= cutoff_ts:
        return None
    if tx.get("transactionError"):
        return None
    target_mint_activity = any(
        change.get("mint") == mint
        for account in tx.get("accountData") or []
        for change in account.get("tokenBalanceChanges") or []
    ) or any(transfer.get("mint") == mint for transfer in tx.get("tokenTransfers") or [])
    if not target_mint_activity:
        return None
    native_lamports = sum(
        int(account.get("nativeBalanceChange") or 0)
        for account in tx.get("accountData") or []
        if account.get("account") == curve
    )
    curve_token_delta = 0.0
    found_balance_delta = False
    for account in tx.get("accountData") or []:
        for change in account.get("tokenBalanceChanges") or []:
            if change.get("mint") == mint and (change.get("userAccount") or account.get("account")) == curve:
                raw = change.get("rawTokenAmount") or {}
                decimals = int(raw.get("decimals") or 0)
                curve_token_delta += as_float(raw.get("tokenAmount")) / (10 ** decimals)
                found_balance_delta = True
    if not found_balance_delta:
        for transfer in tx.get("tokenTransfers") or []:
            if transfer.get("mint") != mint:
                continue
            amount = as_float(transfer.get("tokenAmount"))
            if transfer.get("fromUserAccount") == curve:
                curve_token_delta -= amount
            if transfer.get("toUserAccount") == curve:
                curve_token_delta += amount
    if native_lamports == 0 and abs(curve_token_delta) < 1e-12:
        return None
    native_sol = native_lamports / LAMPORTS_PER_SOL
    implied_price = (abs(native_sol) / abs(curve_token_delta)
                     if native_sol and curve_token_delta else None)
    return {
        "mint": mint, "timestamp": int(ts),
        "timestamp_utc": datetime.fromtimestamp(int(ts), timezone.utc).isoformat(),
        "signature": tx.get("signature"), "slot": tx.get("slot"),
        "curve_native_balance_delta_sol": native_sol,
        "curve_token_balance_delta": curve_token_delta,
        "implied_curve_price_sol_per_token_estimate": implied_price,
        "price_estimate_warning": "Curve account deltas can include fees and multiple transaction legs; this is not a quoted execution price.",
        "liquidity_interpretation": "Relative reserve movement only; absolute reserves are not reconstructed from these deltas.",
    }


def summarize_wallet_events(events: list[dict[str, Any]], creator: str) -> list[dict[str, Any]]:
    wallets: dict[str, dict[str, Any]] = {}
    for event in events:
        wallet = event["wallet"]
        row = wallets.setdefault(wallet, {
            "wallet": wallet, "buy_count": 0, "sell_count": 0,
            "token_bought": 0.0, "token_sold": 0.0,
            "first_seen": event["timestamp"], "last_seen": event["timestamp"],
            "observed_native_delta_sol": 0.0, "creator_wallet": wallet == creator,
        })
        row["first_seen"] = min(row["first_seen"], event["timestamp"])
        row["last_seen"] = max(row["last_seen"], event["timestamp"])
        row["observed_native_delta_sol"] += event["wallet_native_delta_sol"]
        if event["side"] == "BUY":
            row["buy_count"] += 1
            row["token_bought"] += event["token_amount"]
        else:
            row["sell_count"] += 1
            row["token_sold"] += event["token_amount"]
    return sorted(wallets.values(), key=lambda item: item["wallet"])


def main() -> int:
    queue = read_json(COHORT_DIR / "candidate-queue.json", [])
    if not isinstance(queue, list) or not queue:
        raise SystemExit("candidate-queue.json is missing or empty")

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    trades_path = ANALYSIS_DIR / "trade-events.jsonl"
    wallets_path = ANALYSIS_DIR / "wallet-metrics.jsonl"
    coins_path = ANALYSIS_DIR / "coin-metrics.jsonl"
    curve_path = ANALYSIS_DIR / "curve-state.jsonl"
    for path in (trades_path, wallets_path, coins_path, curve_path):
        path.write_text("", encoding="utf-8")

    all_events = []
    coin_rows = []
    total_raw = total_unique = total_failed = total_unclassified = 0
    total_curve_events = 0
    incomplete = []
    parse_errors = 0

    for index, candidate in enumerate(queue, 1):
        mint = candidate["mint"]
        coin_dir = COHORT_DIR / "coins" / mint
        manifest = read_json(coin_dir / "manifest.json", {})
        curve = manifest.get("bonding_curve", "")
        launch_ts = int(candidate["created"])
        cutoff_ts = launch_ts + 3600

        transactions: dict[str, dict[str, Any]] = {}
        raw_count = 0
        duplicate_count = 0
        for address_label in ("mint", "bonding_curve"):
            progress = read_json(coin_dir / address_label / "progress.json", {})
            for page_name in progress.get("page_files", []):
                for tx in read_jsonl(coin_dir / address_label / page_name) or []:
                    raw_count += 1
                    if tx.get("_parse_error"):
                        parse_errors += 1
                        continue
                    signature = tx.get("signature")
                    if not signature:
                        continue
                    if signature in transactions:
                        duplicate_count += 1
                        old = transactions[signature]
                        old_score = len(old.get("tokenTransfers") or []) + sum(
                            len(a.get("tokenBalanceChanges") or []) for a in old.get("accountData") or [])
                        new_score = len(tx.get("tokenTransfers") or []) + sum(
                            len(a.get("tokenBalanceChanges") or []) for a in tx.get("accountData") or [])
                        if new_score > old_score:
                            transactions[signature] = tx
                    else:
                        transactions[signature] = tx

        events = []
        curve_events = []
        cumulative_curve_native = 0.0
        cumulative_curve_token = 0.0
        failed = 0
        unclassified = 0
        in_window = 0
        for tx in transactions.values():
            decoded, quality = decode_transaction(tx, mint, curve, launch_ts, cutoff_ts)
            failed += int(quality["failed"])
            in_window += int(quality["in_window"])
            unclassified += quality["unclassified_wallet_flows"]
            events.extend(decoded)
        for tx in sorted(transactions.values(), key=lambda item: (item.get("timestamp") or 0, item.get("signature") or "")):
            curve_event = decode_curve_state(tx, mint, curve, launch_ts, cutoff_ts)
            if curve_event:
                cumulative_curve_native += curve_event["curve_native_balance_delta_sol"]
                cumulative_curve_token += curve_event["curve_token_balance_delta"]
                curve_event["cumulative_curve_native_delta_sol_from_first_observed"] = cumulative_curve_native
                curve_event["cumulative_curve_token_delta_from_first_observed"] = cumulative_curve_token
                curve_events.append(curve_event)

        events.sort(key=lambda event: (event["timestamp"], event.get("signature") or "", event["wallet"]))
        for curve_event in curve_events:
            append_jsonl(curve_path, curve_event)
        wallet_rows = summarize_wallet_events(events, candidate.get("creator") or "")
        buyers = [row for row in wallet_rows if row["buy_count"] > 0]
        sellers = [row for row in wallet_rows if row["sell_count"] > 0]
        token_bought = sum(row["token_bought"] for row in wallet_rows)
        token_sold = sum(row["token_sold"] for row in wallet_rows)
        top_buy = sorted((row["token_bought"] for row in wallet_rows), reverse=True)
        creator_row = next((row for row in wallet_rows if row["creator_wallet"]), None)
        first10 = {event["wallet"] for event in events
                   if event["side"] == "BUY" and event["timestamp"] <= launch_ts + 10}
        first30 = {event["wallet"] for event in events
                   if event["side"] == "BUY" and event["timestamp"] <= launch_ts + 30}
        mint_progress = read_json(coin_dir / "mint" / "progress.json", {})
        curve_progress = read_json(coin_dir / "bonding_curve" / "progress.json", {})
        is_complete = bool(mint_progress.get("completed") and curve_progress.get("completed"))
        if not is_complete:
            incomplete.append(mint)

        coin = {
            "mint": mint, "creator": candidate.get("creator"),
            "launch_timestamp": launch_ts, "launch_timestamp_utc": datetime.fromtimestamp(launch_ts, timezone.utc).isoformat(),
            "screen_buyers_first_10s": candidate.get("buyers_first_10s"),
            "screen_bundle_supply_share": candidate.get("bundle_supply_share"),
            "mint_history_complete": bool(mint_progress.get("completed")),
            "curve_history_complete": bool(curve_progress.get("completed")),
            "collection_complete": is_complete,
            "mint_pages": mint_progress.get("pages_fetched", 0),
            "curve_pages": curve_progress.get("pages_fetched", 0),
            "mint_raw_transactions_saved": mint_progress.get("transactions_saved", 0),
            "curve_raw_transactions_saved": curve_progress.get("transactions_saved", 0),
            "raw_records_read": raw_count, "unique_signatures": len(transactions),
            "duplicate_records_across_addresses": duplicate_count,
            "transactions_in_window": in_window, "failed_transactions": failed,
            "decoded_buy_events": sum(event["side"] == "BUY" for event in events),
            "decoded_sell_events": sum(event["side"] == "SELL" for event in events),
            "unique_buyers": len({event["wallet"] for event in events if event["side"] == "BUY"}),
            "unique_sellers": len({event["wallet"] for event in events if event["side"] == "SELL"}),
            "unique_buyers_first_10s_reconstructed": len(first10),
            "unique_buyers_first_30s_reconstructed": len(first30),
            "token_amount_bought": token_bought, "token_amount_sold": token_sold,
            "top_1_buyer_share_of_decoded_buys": (top_buy[0] / token_bought if token_bought else None),
            "top_5_buyers_share_of_decoded_buys": (sum(top_buy[:5]) / token_bought if token_bought else None),
            "creator_decoded_buy_count": creator_row["buy_count"] if creator_row else 0,
            "creator_decoded_sell_count": creator_row["sell_count"] if creator_row else 0,
            "unclassified_wallet_flows": unclassified,
            "decoded_trade_events": len(events),
            "curve_state_events": len(curve_events),
            "last_observed_cumulative_curve_native_delta_sol": cumulative_curve_native if curve_events else None,
            "last_observed_cumulative_curve_token_delta": cumulative_curve_token if curve_events else None,
            "data_quality": "COMPLETE_RAW_HISTORY" if is_complete else "INCOMPLETE_RAW_HISTORY",
            "interpretation_warning": "Observed native balance deltas are not trade notional; decoded events are evidence, not a BUY signal or realized PnL.",
        }
        append_jsonl(coins_path, coin)
        for row in wallet_rows:
            append_jsonl(wallets_path, {"mint": mint, **row})
        for event in events:
            append_jsonl(trades_path, event)
        all_events.extend(events)
        coin_rows.append(coin)
        total_raw += raw_count
        total_unique += len(transactions)
        total_failed += failed
        total_unclassified += unclassified
        total_curve_events += len(curve_events)
        if index % 25 == 0:
            print(f"Decoded {index}/{len(queue)} coins...", flush=True)

    summary = {
        "cohort_date_utc": DAY, "cohort_hour_utc": HOUR,
        "coins_in_queue": len(queue),
        "coins_with_complete_raw_history": sum(row["collection_complete"] for row in coin_rows),
        "coins_with_incomplete_raw_history": len(incomplete),
        "incomplete_mints": incomplete,
        "raw_records_read": total_raw, "unique_transaction_signatures": total_unique,
        "duplicate_records_across_mint_and_curve_addresses": total_raw - total_unique,
        "failed_transactions": total_failed, "parse_errors": parse_errors,
        "decoded_buy_events": sum(event["side"] == "BUY" for event in all_events),
        "decoded_sell_events": sum(event["side"] == "SELL" for event in all_events),
        "unique_wallets_in_decoded_events": len({event["wallet"] for event in all_events}),
        "unclassified_wallet_flows": total_unclassified,
        "curve_state_events": total_curve_events,
        "files": {
            "coin_metrics": "analysis/coin-metrics.jsonl",
            "wallet_metrics": "analysis/wallet-metrics.jsonl",
            "trade_events": "analysis/trade-events.jsonl",
            "curve_state": "analysis/curve-state.jsonl",
        },
        "limitations": [
            "This decoder uses Helius token transfers and signed token balance deltas; it does not decode Pump.fun instruction bytes.",
            "A wallet's native balance delta may include fees, priority tips, rent, unrelated transfers, and other transaction legs; it is not asserted as trade notional.",
            "Direct bonding-curve transfer evidence is preferred; signed token/native balance deltas are a fallback and may include non-swap activity.",
            "Transactions that cannot be confidently classified as BUY or SELL are excluded from trade counts and reported as unclassified.",
            "Curve-state output records relative reserve deltas and a rough implied price only when curve native and token deltas coexist; it is not a reliable post-migration market price or absolute liquidity measurement.",
            "No historical quote simulation, slippage model, wallet-cluster attribution, realized PnL, or final BUY decision is produced.",
        ],
        "status": "DECODED_RESEARCH_EVIDENCE_NOT_A_STRATEGY",
    }
    write_json(ANALYSIS_DIR / "analysis-summary.json", summary)
    collection_summary_path = COHORT_DIR / "collection-summary.json"
    collection_summary = read_json(collection_summary_path, {})
    collection_summary["analysis_status"] = summary["status"]
    collection_summary["analysis_outputs"] = summary["files"]
    collection_summary["decoded_buy_events"] = summary["decoded_buy_events"]
    collection_summary["decoded_sell_events"] = summary["decoded_sell_events"]
    collection_summary["curve_state_events"] = summary["curve_state_events"]
    collection_summary["coins_with_incomplete_raw_history"] = summary["coins_with_incomplete_raw_history"]
    collection_summary["limitation"] = "Trade-side evidence is decoded, but native deltas are not trade notional; no execution simulation, realized PnL, or final BUY decision is produced."
    write_json(collection_summary_path, collection_summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
