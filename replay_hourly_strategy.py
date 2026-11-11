#!/usr/bin/env python3
"""Replay the agreed Pump.fun entry/exit rules against a completed hourly cohort.

Uses only target-mint swaps that transfer tokens directly to/from the candidate's
bonding curve and include a Pump.fun program instruction. The curve account's
native balance delta divided by token amount is a price proxy, not a historical
quote. This replay deliberately keeps unavailable cluster/holder/quote checks
unverified rather than treating missing evidence as a pass.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent
DAY = os.environ.get("COHORT_DATE", "2026-11-10")
HOUR = int(os.environ.get("COHORT_HOUR_UTC", "0"))
COHORT_DIR = ROOT / "data" / "hourly" / DAY / f"{HOUR:02d}"
ANALYSIS_DIR = COHORT_DIR / "analysis"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MIGRATE_DISCRIMINATOR = hashlib.sha256(b"global:migrate").digest()[:8]
LAMPORTS_PER_SOL = 1_000_000_000
STANDARD_PUMPFUN_SUPPLY = 1_000_000_000.0

# Agreed entry rules
ENTRY_WINDOW_SECONDS = 60
IMPULSE_MULTIPLE = 1.20
PULLBACK_MIN = 0.10
PULLBACK_MAX = 0.40
RECLAIM_MIN = 0.01
CONFIRM_MIN_SECONDS = 1
CONFIRM_MAX_SECONDS = 2
FLOW_WINDOW_SECONDS = 2
FLOW_WINDOWS_REQUIRED = 3
BUY_SELL_PRESSURE_MIN = 3.0
MIN_UNIQUE_BUYERS_PER_WINDOW = 3
MAX_SELLERS_TO_BUYERS = 0.50
MIN_DISTINCT_BUYERS_ACROSS_WINDOWS = 5
MAX_LARGEST_BUYER_SHARE = 0.72
CREATOR_SELL_REJECT_SUPPLY_SHARE = 0.0005  # 0.05%

# Agreed exit rules
HARD_STOP = 0.05
TRAILING_ACTIVATION = 0.10
TRAILING_GIVEBACK = 0.40
MAX_HOLD_SECONDS = 300
PROFIT_LOCKS = ((0.10, 0.05), (0.50, 0.15), (1.00, 0.40), (2.00, 0.80))
ILLUSTRATIVE_ROUND_TRIP_COST = 0.04


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def b58decode(value: str) -> bytes:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = 0
    for char in value:
        number = number * 58 + alphabet.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + body


def iter_instructions(instructions: list[dict[str, Any]] | None):
    for instruction in instructions or []:
        yield instruction
        yield from iter_instructions(instruction.get("innerInstructions"))


def is_migration_transaction(tx: dict[str, Any]) -> bool:
    for instruction in iter_instructions(tx.get("instructions")):
        if instruction.get("programId") != PUMP_PROGRAM:
            continue
        try:
            if b58decode(instruction.get("data", ""))[:8] == MIGRATE_DISCRIMINATOR:
                return True
        except (ValueError, IndexError):
            continue
    return "MIGRAT" in str(tx.get("type", "")).upper() or "migrat" in str(tx.get("description", "")).lower()


def transaction_score(tx: dict[str, Any]) -> int:
    return (
        len(tx.get("tokenTransfers") or [])
        + sum(len(a.get("tokenBalanceChanges") or []) for a in tx.get("accountData") or [])
        + 2 * sum(1 for _ in iter_instructions(tx.get("instructions")))
    )


def load_coin_history(candidate: dict[str, Any]) -> tuple[list[dict[str, Any]], list[int], dict[str, int]]:
    mint = candidate["mint"]
    coin_dir = COHORT_DIR / "coins" / mint
    manifest = read_json(coin_dir / "manifest.json", {})
    curve = manifest.get("bonding_curve")
    if not curve:
        return [], [], {"unique_transactions": 0, "unpriced_curve_swaps": 0, "non_swap_curve_transfers": 0}

    transactions: dict[str, dict[str, Any]] = {}
    for label in ("mint", "bonding_curve"):
        progress = read_json(coin_dir / label / "progress.json", {})
        for page_name in progress.get("page_files", []):
            for tx in read_jsonl(coin_dir / label / page_name) or []:
                signature = tx.get("signature")
                if not signature:
                    continue
                old = transactions.get(signature)
                if old is None or transaction_score(tx) > transaction_score(old):
                    transactions[signature] = tx

    launch = int(candidate["created"])
    cutoff = launch + 3600
    events: list[dict[str, Any]] = []
    migrations: list[int] = []
    unpriced = 0
    non_swap_transfers = 0

    for tx in transactions.values():
        timestamp = tx.get("timestamp")
        if not isinstance(timestamp, (int, float)) or not launch <= int(timestamp) <= cutoff:
            continue
        if tx.get("transactionError"):
            continue
        relative_time = int(timestamp) - launch
        if is_migration_transaction(tx):
            migrations.append(relative_time)

        transfers = [
            item for item in tx.get("tokenTransfers") or []
            if item.get("mint") == mint
            and (item.get("fromUserAccount") == curve or item.get("toUserAccount") == curve)
        ]
        if not transfers:
            continue
        has_pump_instruction = any(
            instruction.get("programId") == PUMP_PROGRAM
            for instruction in iter_instructions(tx.get("instructions"))
        )
        if tx.get("type") != "SWAP" or not has_pump_instruction:
            non_swap_transfers += 1
            continue

        curve_account = next((
            account for account in tx.get("accountData") or []
            if account.get("account") == curve
        ), None)
        native_change = (curve_account or {}).get("nativeBalanceChange")
        total_tokens = sum(float(item.get("tokenAmount") or 0) for item in transfers)
        directions = {
            "BUY" if item.get("fromUserAccount") == curve else "SELL"
            for item in transfers
        }
        if not native_change or not total_tokens or len(directions) != 1:
            unpriced += 1
            continue
        side = next(iter(directions))
        if (side == "BUY" and native_change <= 0) or (side == "SELL" and native_change >= 0):
            unpriced += 1
            continue

        total_sol = abs(int(native_change)) / LAMPORTS_PER_SOL
        price = total_sol / total_tokens
        for transfer in transfers:
            wallet = transfer.get("toUserAccount") if side == "BUY" else transfer.get("fromUserAccount")
            token_amount = float(transfer.get("tokenAmount") or 0)
            if not wallet or token_amount <= 0:
                continue
            events.append({
                "timestamp": relative_time,
                "side": side,
                "wallet": wallet,
                "token_amount": token_amount,
                "sol_reserve_delta_proxy": total_sol * token_amount / total_tokens,
                "price_proxy_sol_per_token": price,
                "signature": tx.get("signature"),
                "slot": tx.get("slot"),
            })

    events.sort(key=lambda item: (item["timestamp"], item.get("slot") or 0, item.get("signature") or "", item["wallet"]))
    return events, sorted(set(migrations)), {
        "unique_transactions": len(transactions),
        "unpriced_curve_swaps": unpriced,
        "non_swap_curve_transfers": non_swap_transfers,
    }


def build_two_second_windows(events: list[dict[str, Any]], max_seconds: int = 60) -> dict[int, dict[str, Any]]:
    windows: dict[int, dict[str, Any]] = {}
    for index in range(max_seconds // FLOW_WINDOW_SECONDS):
        start = index * FLOW_WINDOW_SECONDS
        windows[index] = {
            "start": start,
            "end": start + FLOW_WINDOW_SECONDS,
            "buys": [],
            "sells": [],
            "buyers": set(),
            "sellers": set(),
            "buy_sol": 0.0,
            "sell_sol": 0.0,
            "token_total": 0.0,
            "sol_total": 0.0,
            "price": None,
        }
    for event in events:
        timestamp = event["timestamp"]
        if not 0 <= timestamp < max_seconds:
            continue
        window = windows[timestamp // FLOW_WINDOW_SECONDS]
        side = event["side"]
        window["buys" if side == "BUY" else "sells"].append(event)
        if side == "BUY":
            window["buyers"].add(event["wallet"])
            window["buy_sol"] += event["sol_reserve_delta_proxy"]
        else:
            window["sellers"].add(event["wallet"])
            window["sell_sol"] += event["sol_reserve_delta_proxy"]
        window["token_total"] += event["token_amount"]
        window["sol_total"] += event["sol_reserve_delta_proxy"]
    for window in windows.values():
        if window["token_total"] > 0:
            window["price"] = window["sol_total"] / window["token_total"]
    return windows


def detect_entry(candidate: dict[str, Any], events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    windows = build_two_second_windows(events)
    populated = [index for index, window in windows.items() if window["price"] is not None]
    diagnostics: dict[str, Any] = {"populated_2s_windows_first_60s": len(populated)}
    if not populated:
        return None, "NO_PRICE_EVENTS_FIRST_60S", diagnostics

    baseline_index = populated[0]
    baseline = windows[baseline_index]["price"]
    impulse_index = None
    for index in populated:
        if windows[index]["price"] >= baseline * IMPULSE_MULTIPLE:
            impulse_index = index
            break
    if impulse_index is None:
        diagnostics["baseline_price_proxy"] = baseline
        return None, "NO_20_PERCENT_IMPULSE", diagnostics

    diagnostics["baseline_price_proxy"] = baseline
    diagnostics["impulse_time_seconds"] = windows[impulse_index]["start"]
    peak = windows[impulse_index]["price"]
    peak_index = impulse_index
    pullback_index = None
    pullback_low = None
    reclaim_index = None
    confirmation_index = None
    failure = "NO_10_TO_40_PERCENT_PULLBACK"

    for index in range(impulse_index + 1, 30):
        price = windows[index]["price"]
        if price is None:
            continue
        if pullback_index is None:
            if price > peak:
                peak = price
                peak_index = index
            drawdown = (peak - price) / peak
            if PULLBACK_MIN <= drawdown <= PULLBACK_MAX:
                pullback_index = index
                pullback_low = price
                failure = "NO_1_PERCENT_RECLAIM"
            elif drawdown > PULLBACK_MAX:
                failure = "PULLBACK_EXCEEDED_40_PERCENT"
                break
        else:
            pullback_low = min(pullback_low, price)
            drawdown = (peak - pullback_low) / peak
            if drawdown > PULLBACK_MAX:
                failure = "PULLBACK_EXCEEDED_40_PERCENT"
                break
            if price >= pullback_low * (1 + RECLAIM_MIN):
                reclaim_index = index
                failure = "NO_1_TO_2_SECOND_CONFIRMATION"
                confirmation_index = reclaim_index + 1
                confirmation = windows.get(confirmation_index)
                if confirmation is None or confirmation["price"] is None:
                    continue
                if confirmation["price"] < pullback_low * (1 + RECLAIM_MIN):
                    continue
                diagnostics.update({
                    "impulse_peak_price_proxy": peak,
                    "impulse_peak_time_seconds": windows[peak_index]["start"],
                    "pullback_time_seconds": windows[pullback_index]["start"],
                    "pullback_low_price_proxy": pullback_low,
                    "reclaim_time_seconds": windows[reclaim_index]["start"],
                    "confirmation_time_seconds": confirmation["start"],
                })
                flow_indices = [confirmation_index + offset for offset in range(1, FLOW_WINDOWS_REQUIRED + 1)]
                flow_windows = [windows.get(i) for i in flow_indices]
                if any(window is None or window["price"] is None for window in flow_windows):
                    diagnostics["flow_windows"] = []
                    return None, "CONFIRMED_BUT_NO_THREE_FLOW_WINDOWS", diagnostics
                if any(window["end"] > ENTRY_WINDOW_SECONDS for window in flow_windows):
                    return None, "CONFIRMED_BUT_FLOW_WINDOWS_AFTER_ENTRY_WINDOW", diagnostics

                all_buyers: set[str] = set()
                buyer_sol: dict[str, float] = defaultdict(float)
                checks = []
                all_flow_pass = True
                for window in flow_windows:
                    buyer_count = len(window["buyers"])
                    seller_count = len(window["sellers"])
                    pressure = (
                        window["buy_sol"] / window["sell_sol"]
                        if window["sell_sol"] > 0
                        else (math.inf if window["buy_sol"] > 0 else 0.0)
                    )
                    pressure_pass = pressure > BUY_SELL_PRESSURE_MIN
                    buyer_pass = buyer_count >= MIN_UNIQUE_BUYERS_PER_WINDOW
                    seller_pass = seller_count <= buyer_count * MAX_SELLERS_TO_BUYERS
                    price_pass = window["price"] >= pullback_low * (1 + RECLAIM_MIN)
                    passed = pressure_pass and buyer_pass and seller_pass and price_pass
                    all_flow_pass = all_flow_pass and passed
                    checks.append({
                        "window_start_seconds": window["start"],
                        "unique_buyers": buyer_count,
                        "unique_sellers": seller_count,
                        "buy_sell_sol_pressure_proxy": None if math.isinf(pressure) else pressure,
                        "buy_sell_pressure_infinite": math.isinf(pressure),
                        "buy_sell_pressure_pass": pressure_pass,
                        "buyer_count_pass": buyer_pass,
                        "seller_count_pass": seller_pass,
                        "reclaim_level_held": price_pass,
                        "window_pass": passed,
                    })
                    all_buyers.update(window["buyers"])
                    for event in window["buys"]:
                        buyer_sol[event["wallet"]] += event["sol_reserve_delta_proxy"]

                total_buy_sol = sum(buyer_sol.values())
                largest_buyer_share = max(buyer_sol.values()) / total_buy_sol if total_buy_sol else 1.0
                diagnostics["flow_windows"] = checks
                diagnostics["distinct_buyers_across_flow_windows"] = len(all_buyers)
                diagnostics["largest_buyer_share_across_flow_windows"] = largest_buyer_share
                diagnostics["five_distinct_buyers_pass"] = len(all_buyers) >= MIN_DISTINCT_BUYERS_ACROSS_WINDOWS
                diagnostics["largest_buyer_share_pass"] = largest_buyer_share <= MAX_LARGEST_BUYER_SHARE

                if all_flow_pass and len(all_buyers) >= MIN_DISTINCT_BUYERS_ACROSS_WINDOWS and largest_buyer_share <= MAX_LARGEST_BUYER_SHARE:
                    last_window = flow_windows[-1]
                    entry = {
                        "entry_time_seconds": last_window["end"],
                        "entry_price_proxy_sol_per_token": last_window["price"],
                        "impulse_time_seconds": windows[impulse_index]["start"],
                        "pullback_time_seconds": windows[pullback_index]["start"],
                        "reclaim_time_seconds": windows[reclaim_index]["start"],
                        "confirmation_time_seconds": confirmation["start"],
                        "flow_window_starts_seconds": [window["start"] for window in flow_windows],
                        "distinct_buyers_across_flow_windows": len(all_buyers),
                        "largest_buyer_share_across_flow_windows": largest_buyer_share,
                    }
                    return entry, "ENTRY_RULES_PASS", diagnostics
                return None, "CONFIRMED_BUT_FLOW_FILTER_FAILED", diagnostics

    diagnostics.update({
        "impulse_peak_price_proxy": peak,
        "impulse_peak_time_seconds": windows[peak_index]["start"],
        "pullback_time_seconds": windows[pullback_index]["start"] if pullback_index is not None else None,
        "pullback_low_price_proxy": pullback_low,
    })
    return None, failure, diagnostics


def simulate_exit(events: list[dict[str, Any]], entry_time: int, entry_price: float,
                  migrations: list[int]) -> dict[str, Any]:
    deadline = entry_time + MAX_HOLD_SECONDS
    migration_time = next((time for time in migrations if entry_time <= time <= deadline), None)
    path = [event for event in events if entry_time <= event["timestamp"] <= deadline]

    if migration_time is not None:
        before_migration = [event for event in path if event["timestamp"] < migration_time]
        exit_event = before_migration[-1] if before_migration else None
        exit_price = exit_event["price_proxy_sol_per_token"] if exit_event else entry_price
        exit_time = migration_time
        exit_reason = "EMERGENCY_MIGRATION_EXIT_PRICE_PROXY"
        high = max([entry_price] + [event["price_proxy_sol_per_token"] for event in before_migration])
    else:
        high = entry_price
        stop = entry_price * (1 - HARD_STOP)
        exit_event = None
        exit_reason = None
        for event in path:
            price = event["price_proxy_sol_per_token"]
            high = max(high, price)
            runup = high / entry_price - 1
            if runup >= TRAILING_ACTIVATION:
                stop = max(stop, entry_price * 1.05, high * (1 - TRAILING_GIVEBACK))
            for activation, floor in PROFIT_LOCKS:
                if runup >= activation:
                    stop = max(stop, entry_price * (1 + floor))
            if price <= stop:
                if high >= entry_price * (1 + TRAILING_ACTIVATION) and stop > entry_price * (1 - HARD_STOP):
                    exit_reason = "TRAILING_STOP_OR_PROFIT_LOCK"
                else:
                    exit_reason = "HARD_STOP"
                exit_event = event
                break
        if exit_event is not None:
            exit_price = exit_event["price_proxy_sol_per_token"]
            exit_time = exit_event["timestamp"]
        elif path:
            exit_event = path[-1]
            exit_price = exit_event["price_proxy_sol_per_token"]
            exit_time = exit_event["timestamp"]
            exit_reason = "MAX_HOLD_MARK_AT_LAST_CURVE_SWAP" if exit_time >= deadline else "LAST_CURVE_SWAP_BEFORE_300S"
        else:
            return {"exit_status": "NO_POST_ENTRY_CURVE_SWAP", "gross_return_pct": None}

    gross_return = exit_price / entry_price - 1
    illustrative_net = (exit_price / entry_price) * (1 - ILLUSTRATIVE_ROUND_TRIP_COST) - 1
    return {
        "exit_status": exit_reason,
        "exit_time_seconds_after_launch": exit_time,
        "exit_price_proxy_sol_per_token": exit_price,
        "highest_price_proxy_sol_per_token": high,
        "maximum_runup_pct": (high / entry_price - 1) * 100,
        "gross_return_pct": gross_return * 100,
        "illustrative_return_after_4pct_round_trip_cost_pct": illustrative_net * 100,
        "cost_note": "Illustrative 4% haircut only; historical impact, tax and actual round-trip costs were not available.",
    }


def summarize_flow_failure(diagnostics: dict[str, Any]) -> list[str]:
    checks = diagnostics.get("flow_windows") or []
    failures = []
    if not checks:
        return ["three 2-second flow windows could not be evaluated"]
    if not all(item.get("buyer_count_pass") for item in checks):
        failures.append("fewer than 3 unique buyers in at least one 2-second window")
    if not all(item.get("buy_sell_pressure_pass") for item in checks):
        failures.append("buy/sell pressure did not exceed 3:1 in every window")
    if not all(item.get("seller_count_pass") for item in checks):
        failures.append("sellers exceeded half the buyers in at least one window")
    if not all(item.get("reclaim_level_held") for item in checks):
        failures.append("price failed the +1% reclaim hold during flow confirmation")
    if not diagnostics.get("five_distinct_buyers_pass", False):
        failures.append("fewer than 5 distinct buyers across the three windows")
    if not diagnostics.get("largest_buyer_share_pass", False):
        failures.append("largest buyer exceeded 72% of buy flow")
    return failures


def outcome_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"trades": 0, "wins": 0, "losses": 0, "median_pct": None, "mean_pct": None}
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "trades": len(values),
        "wins": sum(value > 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "median_pct": median,
        "mean_pct": sum(values) / len(values),
    }


def main() -> int:
    queue = read_json(COHORT_DIR / "candidate-queue.json", [])
    if not queue:
        raise SystemExit(f"Missing or empty candidate queue: {COHORT_DIR}")
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    coin_results = []
    near_misses = []
    entry_status_counts = defaultdict(int)
    official_entries = 0
    official_creator_rejects = 0
    gross_counterfactual: list[float] = []
    net_counterfactual: list[float] = []
    creator_pass_gross: list[float] = []
    creator_pass_net: list[float] = []
    total_valid_swaps = 0
    total_early_swaps = 0
    total_unpriced = 0
    total_non_swap = 0
    total_migrations = 0

    for index, candidate in enumerate(queue, 1):
        events, migrations, quality = load_coin_history(candidate)
        total_valid_swaps += len(events)
        total_early_swaps += sum(event["timestamp"] < ENTRY_WINDOW_SECONDS for event in events)
        total_unpriced += quality["unpriced_curve_swaps"]
        total_non_swap += quality["non_swap_curve_transfers"]
        total_migrations += len(migrations)

        entry, entry_status, diagnostics = detect_entry(candidate, events)
        creator = candidate.get("creator")
        creator_sold_first_minute = sum(
            event["token_amount"] for event in events
            if event["side"] == "SELL" and event["wallet"] == creator
            and event["timestamp"] < ENTRY_WINDOW_SECONDS
        )
        creator_share_first_minute = creator_sold_first_minute / STANDARD_PUMPFUN_SUPPLY
        creator_filter_first_minute = (
            "THRESHOLD_EXCEEDED"
            if creator_share_first_minute > CREATOR_SELL_REJECT_SUPPLY_SHARE
            else "NOT_EXCEEDED"
        )

        row: dict[str, Any] = {
            "mint": candidate["mint"],
            "creator": creator,
            "launch_timestamp": int(candidate["created"]),
            "launch_timestamp_utc": datetime.fromtimestamp(int(candidate["created"]), timezone.utc).isoformat(),
            "first_10s_buyers_initial_screen": candidate.get("buyers_first_10s"),
            "bundle_supply_share_initial_screen": candidate.get("bundle_supply_share"),
            "valid_pumpfun_curve_swap_events_1h": len(events),
            "valid_pumpfun_curve_swap_events_first_60s": sum(event["timestamp"] < ENTRY_WINDOW_SECONDS for event in events),
            "raw_unique_transactions": quality["unique_transactions"],
            "unpriced_curve_swap_candidates": quality["unpriced_curve_swaps"],
            "non_swap_curve_transfers_excluded": quality["non_swap_curve_transfers"],
            "migration_times_seconds_after_launch": migrations,
            "creator_sold_tokens_first_60s": creator_sold_first_minute,
            "creator_sold_supply_pct_first_60s_assuming_1b_supply": creator_share_first_minute * 100,
            "creator_sell_filter_first_60s_diagnostic": creator_filter_first_minute,
            "entry_status": entry_status,
            "entry_diagnostics": diagnostics,
            "official_strategy_trade": None,
            "final_decision": "NO_ENTRY",
            "unverified_safety_and_execution_checks": [
                "creator attribution confidence score >=70%",
                "linked-wallet sell cluster >0.25% supply",
                "high-confidence cluster sell >0.25% supply",
                "cluster buy volume <=35%",
                "cluster holdings <=20%",
                "individual wallet holdings <=20%",
                "entry price impact <=2%",
                "exit price impact <=2%",
                "buy tax <=2% and sell tax <=2%",
                "round-trip execution cost <=4%",
            ],
            "price_data_warning": "Price is curve native-reserve delta divided by directly transferred token amount for Pump.fun swaps; it is not a historical executable quote or guaranteed spot price.",
        }
        entry_status_counts[entry_status] += 1

        if entry is not None:
            creator_sold_before_entry = sum(
                event["token_amount"] for event in events
                if event["side"] == "SELL" and event["wallet"] == creator
                and event["timestamp"] < entry["entry_time_seconds"]
            )
            creator_share_before_entry = creator_sold_before_entry / STANDARD_PUMPFUN_SUPPLY
            creator_filter_at_entry = (
                "REJECT" if creator_share_before_entry > CREATOR_SELL_REJECT_SUPPLY_SHARE
                else "PASS_OBSERVED"
            )
            row["creator_sold_supply_pct_before_entry_assuming_1b_supply"] = creator_share_before_entry * 100
            row["creator_sell_filter_at_entry"] = creator_filter_at_entry
            if creator_filter_at_entry == "REJECT":
                row["final_decision"] = "REJECT_CREATOR_SELL"
                official_creator_rejects += 1
            else:
                exit_result = simulate_exit(
                    events, entry["entry_time_seconds"],
                    entry["entry_price_proxy_sol_per_token"], migrations
                )
                row["official_strategy_trade"] = {"entry": entry, "exit": exit_result}
                row["final_decision"] = "WATCH_UNVERIFIED_SAFETY_AND_EXECUTION"
                official_entries += 1

        elif diagnostics.get("confirmation_time_seconds") is not None:
            # Diagnostic only: omit the mandatory flow gate to measure what it filters.
            confirm_index = diagnostics["confirmation_time_seconds"] // FLOW_WINDOW_SECONDS
            windows = build_two_second_windows(events)
            confirm_window = windows.get(confirm_index)
            if confirm_window and confirm_window.get("price") is not None:
                counter_entry_time = confirm_window["end"]
                counter_entry_price = confirm_window["price"]
                counter_exit = simulate_exit(events, counter_entry_time, counter_entry_price, migrations)
                creator_sold_before_confirm = sum(
                    event["token_amount"] for event in events
                    if event["side"] == "SELL" and event["wallet"] == creator
                    and event["timestamp"] < counter_entry_time
                )
                creator_share_before_confirm = creator_sold_before_confirm / STANDARD_PUMPFUN_SUPPLY
                creator_filter_at_confirm = (
                    "REJECT" if creator_share_before_confirm > CREATOR_SELL_REJECT_SUPPLY_SHARE
                    else "PASS_OBSERVED"
                )
                counter = {
                    "classification": "COUNTERFACTUAL_ONLY_FLOW_FILTER_OMITTED",
                    "entry_time_seconds": counter_entry_time,
                    "entry_price_proxy_sol_per_token": counter_entry_price,
                    "exit": counter_exit,
                    "creator_sold_supply_pct_before_counterfactual_entry_assuming_1b_supply": creator_share_before_confirm * 100,
                    "creator_sell_filter_at_counterfactual_entry": creator_filter_at_confirm,
                    "creator_sell_first_60s_diagnostic": creator_filter_first_minute,
                    "flow_filter_failures": summarize_flow_failure(diagnostics),
                }
                row["counterfactual_without_flow_filter"] = counter
                near_misses.append({"mint": candidate["mint"], **counter})
                if counter_exit.get("gross_return_pct") is not None:
                    gross_counterfactual.append(counter_exit["gross_return_pct"])
                    net_counterfactual.append(counter_exit["illustrative_return_after_4pct_round_trip_cost_pct"])
                    if creator_filter_at_confirm != "REJECT":
                        creator_pass_gross.append(counter_exit["gross_return_pct"])
                        creator_pass_net.append(counter_exit["illustrative_return_after_4pct_round_trip_cost_pct"])

        coin_results.append(row)
        if index % 50 == 0:
            print(f"Replayed {index}/{len(queue)} coins", flush=True)

    flow_diagnostics = [
        row["entry_diagnostics"] for row in coin_results
        if row["entry_diagnostics"].get("flow_windows")
    ]
    flow_failure_summary = {
        "confirmed_setups_with_three_flow_windows_evaluated": len(flow_diagnostics),
        "failed_at_least_one_window_minimum_3_unique_buyers": sum(not all(x.get("buyer_count_pass") for x in d["flow_windows"]) for d in flow_diagnostics),
        "failed_at_least_one_window_buy_sell_pressure_over_3_to_1": sum(not all(x.get("buy_sell_pressure_pass") for x in d["flow_windows"]) for d in flow_diagnostics),
        "failed_at_least_one_window_sellers_at_most_half_buyers": sum(not all(x.get("seller_count_pass") for x in d["flow_windows"]) for d in flow_diagnostics),
        "failed_5_distinct_buyers_across_windows": sum(not d.get("five_distinct_buyers_pass", False) for d in flow_diagnostics),
        "failed_largest_buyer_share_at_most_72pct": sum(not d.get("largest_buyer_share_pass", False) for d in flow_diagnostics),
        "failed_reclaim_level_hold_during_flow_windows": sum(not all(x.get("reclaim_level_held") for x in d["flow_windows"]) for d in flow_diagnostics),
        "maximum_unique_buyers_in_any_window_distribution": {},
    }
    max_buyer_counts = defaultdict(int)
    for diagnostic in flow_diagnostics:
        max_buyer_counts[str(max(x.get("unique_buyers", 0) for x in diagnostic["flow_windows"]))] += 1
    flow_failure_summary["maximum_unique_buyers_in_any_window_distribution"] = dict(max_buyer_counts)

    creator_first_minute_warnings = sum(
        row["creator_sell_filter_first_60s_diagnostic"] == "THRESHOLD_EXCEEDED"
        for row in coin_results
    )
    summary = {
        "cohort_date_utc": DAY,
        "cohort_hour_utc": HOUR,
        "coins_replayed": len(coin_results),
        "valid_pumpfun_curve_swap_events_1h": total_valid_swaps,
        "valid_pumpfun_curve_swap_events_first_60s": total_early_swaps,
        "unpriced_curve_swap_candidates_excluded": total_unpriced,
        "non_swap_curve_transfers_excluded": total_non_swap,
        "migration_instructions_detected": total_migrations,
        "entry_status_counts": dict(entry_status_counts),
        "creator_sell_threshold_exceeded_in_first_60s_diagnostic_count": creator_first_minute_warnings,
        "flow_filter_diagnostics": flow_failure_summary,
        "official_creator_sell_rejects_at_entry": official_creator_rejects,
        "official_strategy_trades": official_entries,
        "official_strategy_win_loss": "NOT_APPLICABLE_NO_ENTRY_PASSED" if official_entries == 0 else "SEE_PER_COIN_RESULTS",
        "counterfactual_without_flow_filter": {
            "note": "Not actual strategy trades. These meet the price setup and 1–2s recheck but omit the mandatory three-window flow gate.",
            "all_confirmed_setups_gross": outcome_summary(gross_counterfactual),
            "all_confirmed_setups_after_illustrative_4pct_cost": outcome_summary(net_counterfactual),
            "creator_filter_pass_gross": outcome_summary(creator_pass_gross),
            "creator_filter_pass_after_illustrative_4pct_cost": outcome_summary(creator_pass_net),
        },
        "entry_rules": {
            "entry_window_seconds": ENTRY_WINDOW_SECONDS,
            "impulse_pct": 20,
            "pullback_pct_range": [10, 40],
            "pivot_reclaim_pct": 1,
            "confirmation_seconds": [CONFIRM_MIN_SECONDS, CONFIRM_MAX_SECONDS],
            "flow_windows": FLOW_WINDOWS_REQUIRED,
            "flow_window_seconds": FLOW_WINDOW_SECONDS,
            "buy_sell_pressure_greater_than": BUY_SELL_PRESSURE_MIN,
            "unique_buyers_per_window_min": MIN_UNIQUE_BUYERS_PER_WINDOW,
            "sellers_max_fraction_of_buyers": MAX_SELLERS_TO_BUYERS,
            "distinct_buyers_across_windows_min": MIN_DISTINCT_BUYERS_ACROSS_WINDOWS,
            "largest_buyer_share_max": MAX_LARGEST_BUYER_SHARE,
        },
        "exit_rules": {
            "hard_stop_pct": -5,
            "trailing_activation_pct": 10,
            "trailing_giveback_pct": 40,
            "profit_lock_floors": {"10%": "5%", "50%": "15%", "100%": "40%", "200%": "80%"},
            "max_hold_seconds": MAX_HOLD_SECONDS,
        },
        "data_and_interpretation_limitations": [
            "The replay uses only complete one-hour raw histories in the cohort.",
            "Swap prices are reserve-delta/token-amount proxies, not archived executable quotes.",
            "SOL pressure uses bonding-curve native reserve deltas, not wallet gross payment amounts.",
            "Historical price impact, taxes, and exact round-trip execution costs are unavailable; the 4% haircut is illustrative only.",
            "Wallet-cluster attribution and point-in-time holder balances are unavailable; those filters remain unverified and cannot be treated as passed.",
            "Creator supply percentage uses the standard 1B-token Pump.fun supply assumption; confirm each mint's actual supply before treating this filter as final.",
            "Post-migration DEX execution prices are not reconstructed; migration exits use the last observed bonding-curve swap price proxy.",
        ],
        "files": {
            "coin_results": "analysis/strategy-replay-coins.jsonl",
            "near_miss_results": "analysis/strategy-replay-near-misses.jsonl",
            "summary": "analysis/strategy-replay-summary.json",
        },
    }

    coin_path = ANALYSIS_DIR / "strategy-replay-coins.jsonl"
    near_path = ANALYSIS_DIR / "strategy-replay-near-misses.jsonl"
    summary_path = ANALYSIS_DIR / "strategy-replay-summary.json"
    with coin_path.open("w", encoding="utf-8") as handle:
        for row in coin_results:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    with near_path.open("w", encoding="utf-8") as handle:
        for row in near_misses:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    csv_path = ANALYSIS_DIR / "strategy-replay-coins.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "mint", "entry_status", "creator_sell_filter_first_60s_diagnostic",
            "creator_sold_supply_pct_first_60s_assuming_1b_supply",
            "valid_pumpfun_curve_swap_events_first_60s",
            "counterfactual_without_flow_filter",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in coin_results:
            counter = row.get("counterfactual_without_flow_filter") or {}
            writer.writerow({
                "mint": row["mint"],
                "entry_status": row["entry_status"],
                "creator_sell_filter_first_60s_diagnostic": row["creator_sell_filter_first_60s_diagnostic"],
                "creator_sold_supply_pct_first_60s_assuming_1b_supply": row["creator_sold_supply_pct_first_60s_assuming_1b_supply"],
                "valid_pumpfun_curve_swap_events_first_60s": row["valid_pumpfun_curve_swap_events_first_60s"],
                "counterfactual_without_flow_filter": counter.get("exit", {}).get("gross_return_pct"),
            })

    print(json.dumps({
        "coins_replayed": len(coin_results),
        "valid_swaps": total_valid_swaps,
        "valid_swaps_first_60s": total_early_swaps,
        "entry_status_counts": dict(entry_status_counts),
        "creator_sell_threshold_exceeded_in_first_60s_diagnostic_count": creator_first_minute_warnings,
        "flow_filter_diagnostics": flow_failure_summary,
        "official_creator_sell_rejects_at_entry": official_creator_rejects,
        "official_strategy_trades": official_entries,
        "near_miss_counterfactuals": len(near_misses),
        "counterfactual_gross": summary["counterfactual_without_flow_filter"]["all_confirmed_setups_gross"],
        "counterfactual_after_4pct": summary["counterfactual_without_flow_filter"]["all_confirmed_setups_after_illustrative_4pct_cost"],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
