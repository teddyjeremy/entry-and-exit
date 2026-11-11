#!/usr/bin/env python3
"""Resumable, read-only Helius collector for Pump.fun token research."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from solders.pubkey import Pubkey

import requests

ROOT = Path(__file__).resolve().parent
TARGETS_FILE = ROOT / "config" / "mints.json"
DATA_ROOT = ROOT / "data"
API_BASE = "https://api-mainnet.helius-rpc.com/v0"
DAS_URL = "https://mainnet.helius-rpc.com"
API_KEY = os.environ.get("HELIUS_API_KEY", "").strip()
PAGE_LIMIT = 100
PAGES_PER_MINT = max(1, min(int(os.environ.get("PAGES_PER_MINT", "10")), 100))
REQUEST_TIMEOUT = 45
PUMP_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
MAX_RETRIES = 5
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "entry-and-exit-research/1.0"})


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, str):
        if API_KEY:
            value = value.replace(API_KEY, '[REDACTED]')
        return re.sub(r'(?i)(api-key=)[^&\\s]+', r'\\1[REDACTED]', value)
    if isinstance(value, dict):
        return {key: redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(url: str, *, params: dict[str, Any] | None = None,
                 payload: dict[str, Any] | None = None) -> Any:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.post(url, params=params, json=payload, timeout=REQUEST_TIMEOUT) if payload is not None else SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2 ** attempt, 30)
                print(f"HTTP {response.status_code}; retrying in {delay:.1f}s", flush=True)
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            delay = min(2 ** attempt, 30)
            print(redact_sensitive(f"Request error ({exc}); retrying in {delay}s"), flush=True)
            time.sleep(delay)
    raise RuntimeError(redact_sensitive(f"Helius request failed after {MAX_RETRIES} attempts: {last_error}"))


def collect_asset(mint: str, mint_dir: Path) -> None:
    path = mint_dir / "asset.json"
    if path.exists():
        print(f"Asset metadata already exists for {mint}")
        return
    url = f"{DAS_URL}/?api-key={API_KEY}"
    try:
        result = request_json(url, payload={
            "jsonrpc": "2.0",
            "id": "entry-and-exit-research",
            "method": "getAsset",
            "params": {"id": mint}
        })
        write_json(path, {
            "collected_at": utc_now(),
            "mint": mint,
            "response": result
        })
    except Exception as exc:
        # Metadata failure should not prevent transaction-history collection.
        safe_error = redact_sensitive(str(exc))
        write_json(mint_dir / "asset_error.json", {
            "collected_at": utc_now(),
            "mint": mint,
            "error": safe_error
        })
        print(f"WARNING: metadata request failed for {mint}: {safe_error}", file=sys.stderr)


def derive_bonding_curve(mint: str) -> str:
    mint_pubkey = Pubkey.from_string(mint)
    curve, _bump = Pubkey.find_program_address([b"bonding-curve", bytes(mint_pubkey)], PUMP_PROGRAM_ID)
    return str(curve)


def collect_history(address: str, label: str, mint_dir: Path, history_dir: Path | None = None) -> None:
    history_dir = history_dir or mint_dir
    checkpoint_path = history_dir / "checkpoint.json"
    checkpoint = read_json(checkpoint_path, {
        "address": address,
        "label": label,
        "next_before_signature": None,
        "pages_collected": 0,
        "transactions_collected": 0,
        "completed": False,
        "started_at": utc_now()
    })

    if checkpoint.get("completed"):
        print(f"History already complete for {label} ({address})")
        return

    pages_this_run = 0
    while pages_this_run < PAGES_PER_MINT:
        params: dict[str, Any] = {
            "api-key": API_KEY,
            "limit": PAGE_LIMIT,
            "sort-order": "desc",
            "commitment": "finalized"
        }
        cursor = checkpoint.get("next_before_signature")
        if cursor:
            params["before-signature"] = cursor

        url = f"{API_BASE}/addresses/{address}/transactions"
        records = request_json(url, params=params)

        if isinstance(records, dict) and records.get("error"):
            raise RuntimeError(f"Helius API error for {address}: {records}")
        if not isinstance(records, list):
            raise RuntimeError(f"Unexpected history response for {address}: {type(records).__name__}")

        if not records:
            checkpoint["completed"] = True
            checkpoint["completion_reason"] = "empty_page_confirmed"
            checkpoint["completed_at"] = utc_now()
            write_json(checkpoint_path, checkpoint)
            print(f"No more history for {label}; empty page confirmed completion.")
            break

        last_signature = records[-1].get("signature")
        if not last_signature:
            raise RuntimeError(f"Last record has no signature; refusing to save or advance checkpoint for {address}")
        if last_signature == cursor:
            raise RuntimeError(f"Pagination cursor did not advance for {address}; refusing to duplicate a page")

        page_number = int(checkpoint["pages_collected"]) + 1
        page_path = history_dir / "transactions" / f"page-{page_number:06d}.jsonl"
        page_path.parent.mkdir(parents=True, exist_ok=True)

        # Persist page first. Only then advance the cursor checkpoint.
        with page_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


        checkpoint["next_before_signature"] = last_signature
        checkpoint["pages_collected"] = page_number
        checkpoint["transactions_collected"] = int(checkpoint["transactions_collected"]) + len(records)
        checkpoint["last_page_count"] = len(records)
        checkpoint["last_signature"] = last_signature
        checkpoint["last_collected_at"] = utc_now()
        # A short page is not proof that history ended; require a subsequent empty page.
        checkpoint["completed"] = False
        checkpoint["completion_reason"] = (
            "short_page_requires_empty_confirmation" if len(records) < PAGE_LIMIT
            else "more_pages_may_exist"
        )
        write_json(checkpoint_path, checkpoint)

        pages_this_run += 1
        print(
            f"{label}: saved page {page_number} ({len(records)} txs); "
            f"total={checkpoint['transactions_collected']}; "
            f"completed={checkpoint['completed']}",
            flush=True
        )
        if checkpoint["completed"]:
            break
        time.sleep(0.25)

    print(f"Checkpoint for {label}: {json.dumps(checkpoint, sort_keys=True)}")


def main() -> int:
    if not API_KEY:
        print("ERROR: HELIUS_API_KEY is not set. Add it under Settings → Secrets and variables → Actions.", file=sys.stderr)
        return 2
    if not TARGETS_FILE.exists():
        print(f"ERROR: targets file not found: {TARGETS_FILE}", file=sys.stderr)
        return 2

    config = read_json(TARGETS_FILE, {})
    targets = config.get("targets", [])
    if not targets:
        print("ERROR: no targets configured.", file=sys.stderr)
        return 2

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    run_manifest = {
        "run_started_at": utc_now(),
        "collector_version": 1,
        "helius_api": "Enhanced Transactions address history + DAS getAsset",
        "page_limit": PAGE_LIMIT,
        "pages_per_mint_this_run": PAGES_PER_MINT,
        "targets": []
    }

    for target in targets:
        mint = target["mint"]
        label = target["label"]
        mint_dir = DATA_ROOT / label
        mint_dir.mkdir(parents=True, exist_ok=True)
        print(f"Collecting {label}: {mint}", flush=True)
        collect_asset(mint, mint_dir)
        collect_history(mint, label, mint_dir)
        curve_checkpoint = None
        if target.get("collect_curve_history", False):
            curve_address = derive_bonding_curve(mint)
            print(f"Derived Pump.fun bonding curve for {label}: {curve_address}", flush=True)
            curve_dir = mint_dir / "bonding_curve"
            collect_history(curve_address, f"{label}_bonding_curve", mint_dir, curve_dir)
            curve_checkpoint = read_json(curve_dir / "checkpoint.json", {})
        checkpoint = read_json(mint_dir / "checkpoint.json", {})
        run_manifest["targets"].append({
            "label": label,
            "mint": mint,
            "pages_collected": checkpoint.get("pages_collected", 0),
            "transactions_collected": checkpoint.get("transactions_collected", 0),
            "completed": checkpoint.get("completed", False),
            "bonding_curve_address": curve_address if target.get("collect_curve_history", False) else None,
            "bonding_curve_transactions": curve_checkpoint.get("transactions_collected", 0) if curve_checkpoint else 0,
            "bonding_curve_completed": curve_checkpoint.get("completed", False) if curve_checkpoint else False
        })

    run_manifest["run_finished_at"] = utc_now()
    write_json(DATA_ROOT / "latest-run.json", run_manifest)
    print(json.dumps(run_manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
