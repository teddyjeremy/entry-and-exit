#!/usr/bin/env python3
"""Build a UTC launch-hour cohort and collect at most each coin's first hour.

This is a research collector, not a trading bot. The initial rules only create
REJECTED / WATCH / SHORTLISTED records; no record is a BUY recommendation.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data" / "hourly"
PUMP_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "").strip()
DAY = os.environ.get("COHORT_DATE", "2026-11-10")
HOUR = int(os.environ.get("COHORT_HOUR_UTC", "0"))
MIN_BUYERS_10S = int(os.environ.get("MIN_BUYERS_10S", "3"))
MAX_BUNDLE_SHARE = float(os.environ.get("MAX_BUNDLE_SHARE", "0.35"))
MAX_PAGES_PER_ADDRESS = int(os.environ.get("MAX_PAGES_PER_ADDRESS", "20"))
PAGE_SIZE = 100
TIMEOUT = 45
BASE = "https://api-mainnet.helius-rpc.com/v0"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "entry-and-exit-hourly-research/1.1"})


def utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    for attempt in range(6):
        response = SESSION.get(url, params=params, timeout=TIMEOUT)
        if response.status_code == 429 or response.status_code >= 500:
            delay = min(2 ** attempt, 30)
            print(f"HTTP {response.status_code}; retrying in {delay}s", flush=True)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Request failed after retries: {url}")


def classify_coin(coin: dict[str, Any]) -> tuple[str, str | None]:
    """Return an auditable first-pass status and reason."""
    try:
        buyers = int(coin.get("buyers_first_10s") or 0)
    except (TypeError, ValueError):
        buyers = 0
    if buyers < MIN_BUYERS_10S:
        return "REJECTED", "INSUFFICIENT_FIRST_10S_BUYERS"

    bundle = coin.get("bundle_supply_share")
    if bundle is None:
        return "WATCH", "MISSING_BUNDLE_EVIDENCE"
    try:
        bundle_share = float(bundle)
    except (TypeError, ValueError):
        return "WATCH", "INVALID_BUNDLE_EVIDENCE"
    if not 0 <= bundle_share <= 1:
        return "WATCH", "INVALID_BUNDLE_EVIDENCE"
    if bundle_share > MAX_BUNDLE_SHARE:
        return "REJECTED", "HIGH_EARLY_SUPPLY_CONCENTRATION"
    return "SHORTLISTED_FOR_DEEP_COLLECTION", None


def derive_curve(mint: str) -> str:
    mint_key = Pubkey.from_string(mint)
    curve, _ = Pubkey.find_program_address(
        [b"bonding-curve", bytes(mint_key)], PUMP_PROGRAM_ID
    )
    return str(curve)


def collect_address_history(address: str, label: str, mint_dir: Path,
                            launch_ts: int, cutoff_ts: int) -> dict[str, Any]:
    out = mint_dir / label
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (old.get("completed")
                and old.get("window_start") == launch_ts
                and old.get("window_end") == cutoff_ts):
            return old

    before = None
    pages_fetched = 0
    saved = 0
    reached_start = False
    page_files: list[str] = []
    for _ in range(MAX_PAGES_PER_ADDRESS):
        params: dict[str, Any] = {
            "api-key": HELIUS_API_KEY,
            "limit": PAGE_SIZE,
            "sort-order": "desc",
            "commitment": "finalized",
        }
        if before:
            params["before-signature"] = before
        records = get_json(f"{BASE}/addresses/{address}/transactions", params)
        if not isinstance(records, list):
            raise RuntimeError(f"Unexpected Helius response for {address}: {records!r}")
        if not records:
            reached_start = True
            break
        pages_fetched += 1

        in_window = []
        times = []
        for record in records:
            ts = record.get("timestamp")
            if isinstance(ts, (int, float)):
                ts = int(ts)
                times.append(ts)
                if launch_ts <= ts <= cutoff_ts:
                    in_window.append(record)

        if in_window:
            page_name = f"page-{pages_fetched:04d}.jsonl"
            with (out / page_name).open("w", encoding="utf-8") as f:
                for item in in_window:
                    f.write(json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n")
            page_files.append(page_name)
            saved += len(in_window)

        # Helius is requested newest-first; once a page reaches before launch,
        # older pages cannot contain any more records in this coin's window.
        if times and min(times) < launch_ts:
            reached_start = True
            break
        if len(records) < PAGE_SIZE:
            reached_start = True
            break
        before = records[-1].get("signature")
        if not before:
            break
        time.sleep(0.15)

    result = {
        "address": address,
        "label": label,
        "window_start": launch_ts,
        "window_start_utc": utc_iso(launch_ts),
        "window_end": cutoff_ts,
        "window_end_utc": utc_iso(cutoff_ts),
        "transactions_saved": saved,
        "pages_fetched": pages_fetched,
        "pages_with_window_transactions": len(page_files),
        "page_files": page_files,
        "reached_start_of_window": reached_start,
        "completed": reached_start,
        "page_limit_hit": not reached_start and pages_fetched >= MAX_PAGES_PER_ADDRESS,
    }
    write_json(manifest_path, result)
    return result


def main() -> int:
    try:
        day_dt = datetime.strptime(DAY, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print("COHORT_DATE must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if not 0 <= HOUR <= 23:
        print("COHORT_HOUR_UTC must be 0..23", file=sys.stderr)
        return 2
    if not HELIUS_API_KEY:
        print("HELIUS_API_KEY is not set", file=sys.stderr)
        return 2
    if MAX_PAGES_PER_ADDRESS < 1:
        print("MAX_PAGES_PER_ADDRESS must be at least 1", file=sys.stderr)
        return 2

    start_ts = int(day_dt.timestamp()) + HOUR * 3600
    end_ts = start_ts + 3600
    cohort_dir = DATA_ROOT / DAY / f"{HOUR:02d}"
    cohort_dir.mkdir(parents=True, exist_ok=True)

    dataset = get_json(f"https://pumpdata.fun/launches/{DAY}.json")
    columns = dataset.get("columns", [])
    rows = dataset.get("launches", [])
    if not columns or not isinstance(rows, list):
        raise RuntimeError("Unexpected pumpdata launch dataset schema")
    index = {name: i for i, name in enumerate(columns)}
    required = ["mint", "created", "creator", "buyers_first_10s", "bundle_supply_share"]
    missing = [name for name in required if name not in index]
    if missing:
        raise RuntimeError(f"Launch dataset is missing columns: {missing}")

    hour_launches = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            continue
        coin = dict(zip(columns, row))
        try:
            created = int(coin["created"])
        except (TypeError, ValueError):
            continue
        if start_ts <= created < end_ts:
            hour_launches.append(coin)
    hour_launches.sort(key=lambda x: (int(x["created"]), x["mint"]))

    ledger_path = cohort_dir / "cohort.jsonl"
    if ledger_path.exists():
        ledger_path.unlink()
    candidates: list[tuple[dict[str, Any], str]] = []
    counts: dict[str, int] = {}
    for coin in hour_launches:
        status, reason = classify_coin(coin)
        launch_ts = int(coin["created"])
        record = {
            **coin,
            "cohort_date_utc": DAY,
            "cohort_hour_utc": HOUR,
            "launch_time_utc": utc_iso(launch_ts),
            "collection_window_start_utc": utc_iso(launch_ts),
            "collection_window_end_utc": utc_iso(launch_ts + 3600),
            "status": status,
            "rejection_reason": reason,
            "final_entry_decision": "NOT_EVALUATED",
        }
        append_jsonl(ledger_path, record)
        counts[status] = counts.get(status, 0) + 1
        # WATCH rows are collected too, so missing/invalid evidence can be
        # investigated rather than silently discarded.
        if status in ("SHORTLISTED_FOR_DEEP_COLLECTION", "WATCH"):
            candidates.append((coin, status))

    write_json(cohort_dir / "cohort-summary.json", {
        "date_utc": DAY,
        "hour_utc": HOUR,
        "window_start_utc": utc_iso(start_ts),
        "window_end_utc_exclusive": utc_iso(end_ts),
        "dataset_complete": dataset.get("complete"),
        "dataset_complete_to": dataset.get("complete_to"),
        "launches_in_hour": len(hour_launches),
        "status_counts": counts,
        "coins_selected_for_deep_collection": len(candidates),
        "screening_rules": {
            "minimum_buyers_first_10s": MIN_BUYERS_10S,
            "maximum_bundle_supply_share": MAX_BUNDLE_SHARE,
            "missing_or_invalid_bundle_evidence": "WATCH, not REJECTED",
        },
        "important": "SHORTLISTED and WATCH are research states, not BUY signals. Full entry rules are not evaluated here.",
    })

    manifests = []
    for number, (coin, screening_status) in enumerate(candidates, start=1):
        mint = coin["mint"]
        launch_ts = int(coin["created"])
        cutoff_ts = launch_ts + 3600
        mint_dir = cohort_dir / "coins" / mint
        mint_dir.mkdir(parents=True, exist_ok=True)
        curve = derive_curve(mint)
        print(f"[{number}/{len(candidates)}] {screening_status}: collecting {mint}", flush=True)
        mint_result = collect_address_history(mint, "mint", mint_dir, launch_ts, cutoff_ts)
        curve_result = collect_address_history(curve, "bonding_curve", mint_dir, launch_ts, cutoff_ts)
        manifest = {
            "mint": mint,
            "creator": coin.get("creator"),
            "created": launch_ts,
            "created_utc": utc_iso(launch_ts),
            "screening_status": screening_status,
            "data_cutoff": cutoff_ts,
            "data_cutoff_utc": utc_iso(cutoff_ts),
            "bonding_curve": curve,
            "mint_history": mint_result,
            "curve_history": curve_result,
            "collection_status": "COMPLETE" if mint_result["completed"] and curve_result["completed"] else "INCOMPLETE",
        }
        write_json(mint_dir / "manifest.json", manifest)
        manifests.append(manifest)

    write_json(cohort_dir / "collection-summary.json", {
        "date_utc": DAY,
        "hour_utc": HOUR,
        "selected_for_deep_collection": len(candidates),
        "coins_with_complete_history": sum(x["collection_status"] == "COMPLETE" for x in manifests),
        "coins_with_incomplete_history": sum(x["collection_status"] != "COMPLETE" for x in manifests),
        "history_manifests": manifests,
        "data_window_rule": "Only timestamps from each coin's created timestamp through created+3600 seconds, inclusive, are written.",
        "limitation": "Raw mint and bonding-curve address histories are not decoded into trades here. No PnL or final entry decision is produced.",
    })
    print(json.dumps({
        "hour_launches": len(hour_launches),
        "status_counts": counts,
        "selected_for_deep_collection": len(candidates),
        "output": str(cohort_dir.relative_to(ROOT)),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
