#!/usr/bin/env python3
"""Screen a UTC launch-hour cohort and collect only a small qualified shortlist.

The cohort index is lightweight. Deep Helius history is limited to the top
MAX_DEEP_CANDIDATES qualifying launches and is persisted in resumable batches.
This is research evidence, not a BUY signal or PnL calculation.
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
MIN_BUYERS_10S = int(os.environ.get("MIN_BUYERS_10S", "5"))
MAX_BUNDLE_SHARE = float(os.environ.get("MAX_BUNDLE_SHARE", "0.20"))
MAX_DEEP_CANDIDATES = int(os.environ.get("MAX_DEEP_CANDIDATES", "50"))
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))
MAX_PAGES_PER_ADDRESS = int(os.environ.get("MAX_PAGES_PER_ADDRESS", "20"))
PAGE_SIZE = 100
TIMEOUT = 45
BASE = "https://api-mainnet.helius-rpc.com/v0"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "entry-and-exit-hourly-research/2.0"})


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
    for attempt in range(10):
        response = SESSION.get(url, params=params, timeout=TIMEOUT)
        if response.status_code == 429 or response.status_code >= 500:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(2 ** attempt, 60)
            except ValueError:
                delay = min(2 ** attempt, 60)
            delay = min(max(delay, 1), 120)
            print(f"HTTP {response.status_code}; retrying in {delay:g}s (attempt {attempt + 1}/10)", flush=True)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"Request failed after 10 retries: {url}")


def classify_coin(coin: dict[str, Any]) -> tuple[str, str | None]:
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
        return "REJECTED", "BUNDLE_SUPPLY_SHARE_ABOVE_LIMIT"
    return "QUALIFIED", None


def derive_curve(mint: str) -> str:
    mint_key = Pubkey.from_string(mint)
    curve, _ = Pubkey.find_program_address([b"bonding-curve", bytes(mint_key)], PUMP_PROGRAM_ID)
    return str(curve)


def collect_address_history(address: str, label: str, mint_dir: Path,
                            launch_ts: int, cutoff_ts: int) -> dict[str, Any]:
    out = mint_dir / label
    out.mkdir(parents=True, exist_ok=True)
    progress_path = out / "progress.json"
    progress = {}
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if (progress.get("completed")
                and progress.get("window_start") == launch_ts
                and progress.get("window_end") == cutoff_ts):
            return progress

    before = progress.get("before_signature")
    pages_fetched = int(progress.get("pages_fetched", 0))
    saved = int(progress.get("transactions_saved", 0))
    reached_start = bool(progress.get("reached_start_of_window", False))
    page_files = list(progress.get("page_files", []))

    while not reached_start and pages_fetched < MAX_PAGES_PER_ADDRESS:
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

        page_name = f"page-{pages_fetched:04d}.jsonl"
        if in_window:
            with (out / page_name).open("w", encoding="utf-8") as f:
                for item in in_window:
                    f.write(json.dumps(item, separators=(",", ":"), sort_keys=True) + "\n")
            page_files.append(page_name)
            saved += len(in_window)

        if times and min(times) < launch_ts:
            reached_start = True
        elif len(records) < PAGE_SIZE:
            reached_start = True
        else:
            before = records[-1].get("signature")
            if not before:
                reached_start = True

        progress = {
            "address": address, "label": label,
            "window_start": launch_ts, "window_start_utc": utc_iso(launch_ts),
            "window_end": cutoff_ts, "window_end_utc": utc_iso(cutoff_ts),
            "transactions_saved": saved, "pages_fetched": pages_fetched,
            "page_files": page_files, "before_signature": before,
            "reached_start_of_window": reached_start,
            "completed": reached_start,
            "page_limit_hit": not reached_start and pages_fetched >= MAX_PAGES_PER_ADDRESS,
        }
        write_json(progress_path, progress)
        if not reached_start:
            time.sleep(1.0)

    return progress or {
        "address": address, "label": label, "window_start": launch_ts,
        "window_end": cutoff_ts, "transactions_saved": 0, "pages_fetched": 0,
        "page_files": [], "reached_start_of_window": reached_start,
        "completed": reached_start, "page_limit_hit": False,
    }


def build_cohort(dataset: dict[str, Any], cohort_dir: Path, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
    columns = dataset.get("columns", [])
    rows = dataset.get("launches", [])
    if not columns or not isinstance(rows, list):
        raise RuntimeError("Unexpected pumpdata launch dataset schema")
    index = {name: i for i, name in enumerate(columns)}
    required = ["mint", "created", "creator", "buyers_first_10s", "bundle_supply_share"]
    missing = [name for name in required if name not in index]
    if missing:
        raise RuntimeError(f"Launch dataset is missing columns: {missing}")

    launches = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            continue
        coin = dict(zip(columns, row))
        try:
            created = int(coin["created"])
        except (TypeError, ValueError):
            continue
        if start_ts <= created < end_ts:
            launches.append(coin)
    launches.sort(key=lambda x: (int(x["created"]), x["mint"]))

    evaluated = []
    qualified = []
    counts: dict[str, int] = {}
    for coin in launches:
        status, reason = classify_coin(coin)
        coin = dict(coin)
        coin["screen_status"] = status
        coin["screen_reason"] = reason
        counts[status] = counts.get(status, 0) + 1
        if status == "QUALIFIED":
            qualified.append(coin)
        evaluated.append(coin)

    # Deterministic prioritization: strongest first-10s buyer count, then
    # lowest disclosed bundle share, then earliest launch. No random sampling.
    qualified.sort(key=lambda x: (
        -int(x.get("buyers_first_10s") or 0),
        float(x.get("bundle_supply_share")),
        int(x["created"]),
        x["mint"],
    ))
    selected = qualified[:MAX_DEEP_CANDIDATES]
    selected_mints = {x["mint"] for x in selected}

    ledger = cohort_dir / "cohort.jsonl"
    ledger_tmp = ledger.with_suffix(".jsonl.tmp")
    with ledger_tmp.open("w", encoding="utf-8") as f:
        for coin in evaluated:
            launch_ts = int(coin["created"])
            status = coin["screen_status"]
            if status == "QUALIFIED":
                status = "SHORTLISTED_FOR_DEEP_COLLECTION" if coin["mint"] in selected_mints else "QUALIFIED_OVER_COLLECTION_CAP"
            record = {
                **coin,
                "cohort_date_utc": DAY, "cohort_hour_utc": HOUR,
                "launch_time_utc": utc_iso(launch_ts),
                "collection_window_start_utc": utc_iso(launch_ts),
                "collection_window_end_utc": utc_iso(launch_ts + 3600),
                "status": status, "rejection_reason": coin["screen_reason"],
                "final_entry_decision": "NOT_EVALUATED",
            }
            f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")
    ledger_tmp.replace(ledger)

    write_json(cohort_dir / "cohort-summary.json", {
        "date_utc": DAY, "hour_utc": HOUR,
        "window_start_utc": utc_iso(start_ts), "window_end_utc_exclusive": utc_iso(end_ts),
        "dataset_complete": dataset.get("complete"), "dataset_complete_to": dataset.get("complete_to"),
        "launches_in_hour": len(launches), "initial_screen_counts": counts,
        "qualified_before_cap": len(qualified), "selected_for_deep_collection": len(selected),
        "qualified_not_collected_due_to_cap": max(0, len(qualified) - len(selected)),
        "screening_rules": {
            "minimum_buyers_first_10s": MIN_BUYERS_10S,
            "maximum_bundle_supply_share": MAX_BUNDLE_SHARE,
            "missing_or_invalid_bundle_evidence": "WATCH; not deep-collected",
            "deep_collection_cap": MAX_DEEP_CANDIDATES,
            "priority": "buyers_first_10s descending, bundle share ascending, launch time ascending",
        },
        "important": "This is a strict first-pass research screen only. It does not evaluate decoded buy/sell pressure, wallet clusters, liquidity, execution costs, or BUY eligibility.",
    })
    write_json(cohort_dir / "candidate-queue.json", [
        {"mint": c["mint"], "creator": c.get("creator"), "created": int(c["created"]),
         "buyers_first_10s": c.get("buyers_first_10s"),
         "bundle_supply_share": c.get("bundle_supply_share")}
        for c in selected
    ])
    return selected


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
    if min(MAX_PAGES_PER_ADDRESS, BATCH_SIZE, MAX_DEEP_CANDIDATES) < 1:
        print("Page, batch, and candidate limits must be at least 1", file=sys.stderr)
        return 2

    start_ts = int(day_dt.timestamp()) + HOUR * 3600
    end_ts = start_ts + 3600
    cohort_dir = DATA_ROOT / DAY / f"{HOUR:02d}"
    cohort_dir.mkdir(parents=True, exist_ok=True)
    queue_path = cohort_dir / "candidate-queue.json"

    if queue_path.exists():
        candidates = json.loads(queue_path.read_text(encoding="utf-8"))
    else:
        dataset = get_json(f"https://pumpdata.fun/launches/{DAY}.json")
        candidates = build_cohort(dataset, cohort_dir, start_ts, end_ts)

    checkpoint_path = cohort_dir / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {"next_index": 0}
    next_index = int(checkpoint.get("next_index", 0))
    end_index = min(next_index + BATCH_SIZE, len(candidates))
    print(f"Cohort: {DAY} {HOUR:02d}:00 UTC | selected: {len(candidates)} | processing {next_index + 1 if next_index < end_index else next_index}/{len(candidates)} through {end_index}", flush=True)

    manifests = []
    for i in range(next_index, end_index):
        coin = candidates[i]
        mint = coin["mint"]
        launch_ts = int(coin["created"])
        cutoff_ts = launch_ts + 3600
        mint_dir = cohort_dir / "coins" / mint
        mint_dir.mkdir(parents=True, exist_ok=True)
        curve = derive_curve(mint)
        print(f"[{i + 1}/{len(candidates)}] collecting qualified coin {mint}", flush=True)
        mint_result = collect_address_history(mint, "mint", mint_dir, launch_ts, cutoff_ts)
        write_json(mint_dir / "manifest.json", {
            "mint": mint, "creator": coin.get("creator"), "created": launch_ts,
            "created_utc": utc_iso(launch_ts), "screening_status": "SHORTLISTED_FOR_DEEP_COLLECTION",
            "bonding_curve": curve, "data_cutoff": cutoff_ts,
            "mint_history": mint_result, "collection_status": "MINT_COMPLETE" if mint_result.get("completed") else "MINT_INCOMPLETE",
        })
        curve_result = collect_address_history(curve, "bonding_curve", mint_dir, launch_ts, cutoff_ts)
        manifest = {
            "mint": mint, "creator": coin.get("creator"), "created": launch_ts,
            "created_utc": utc_iso(launch_ts), "screening_status": "SHORTLISTED_FOR_DEEP_COLLECTION",
            "data_cutoff": cutoff_ts, "data_cutoff_utc": utc_iso(cutoff_ts),
            "bonding_curve": curve, "mint_history": mint_result, "curve_history": curve_result,
            "collection_status": "COMPLETE" if mint_result.get("completed") and curve_result.get("completed") else "INCOMPLETE",
        }
        write_json(mint_dir / "manifest.json", manifest)
        manifests.append(manifest)
        checkpoint = {"next_index": i + 1, "candidate_count": len(candidates),
                      "completed_this_batch": len(manifests), "updated_at_utc": datetime.now(timezone.utc).isoformat()}
        write_json(checkpoint_path, checkpoint)

    remaining = end_index < len(candidates)
    write_json(cohort_dir / "collection-summary.json", {
        "date_utc": DAY, "hour_utc": HOUR, "selected_for_deep_collection": len(candidates),
        "processed_candidates": end_index, "remaining_candidates": len(candidates) - end_index,
        "coins_with_complete_history": sum(1 for c in candidates[:end_index]
            if (cohort_dir / "coins" / c["mint"] / "manifest.json").exists()
            and json.loads((cohort_dir / "coins" / c["mint"] / "manifest.json").read_text()).get("collection_status") == "COMPLETE"),
        "batch_size": BATCH_SIZE, "next_index": end_index,
        "data_window_rule": "Only transactions with timestamps from launch through launch+3600 seconds inclusive are saved.",
        "limitation": "Raw address transactions are not yet decoded into swaps/trades; no PnL or final entry decision is produced.",
        "complete": not remaining,
    })
    print(json.dumps({"launches_selected": len(candidates), "processed": end_index,
                      "remaining": len(candidates) - end_index, "output": str(cohort_dir.relative_to(ROOT))}, indent=2))
    return 10 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())

# Trigger the corrected resumable cohort workflow after merge.

# Ensure a newly merged run exercises latest-main checkpoint sync.
