# Pump.fun coin research collector

This repository collects Helius on-chain evidence for failed Pump.fun launches so we can infer **evidence-backed coin rejection rules**. It does not implement or modify the trading entry/exit strategy.

## What it collects

- Helius Enhanced transaction history for each configured token mint (paginated, newest to oldest).
- Helius DAS asset metadata for each mint.
- Raw parsed transaction records as JSONL, one file per page.
- Per-mint checkpoints, including the last signature, page count, and completion state.
- A GitHub Actions artifact containing the collected data for convenient download.

The collector deliberately preserves the full parsed transaction response. We will derive creator, bonding-curve, wallet-cluster, buy/sell-flow, holder-distribution, and lifecycle evidence from the data rather than hardcoding assumptions in advance.

## Configure

1. In GitHub, open **Settings → Secrets and variables → Actions**.
2. Add a repository secret named `HELIUS_API_KEY`.
3. Open **Actions → Helius coin research → Run workflow**.
4. Run again whenever needed. The collector resumes from the committed checkpoint.
5. Download the `helius-research-data` artifact from the workflow run, or let the next run continue collecting.

The API key is never written to the repository or artifact.

## Resumability and storage

- Durable source of truth: `data/` committed to the default branch.
- Convenient snapshot: `helius-research-data` Actions artifact.
- Each invocation collects up to 10 pages per mint by default. Re-running continues from the saved signature cursor.
- Pages are written before the checkpoint is advanced. If a run is interrupted, already committed pages are not fetched again.
- Raw data is not deduplicated or transformed beyond JSONL serialization.

## Current target set

The three supplied failed coins are in `config/mints.json`. Successful comparison coins can be added later after we agree on a measurable outcome definition.

## Important scope note

The first pass scans transaction history associated with each mint address. Some Pump.fun trading activity may be more completely represented by the bonding-curve account and related accounts discovered from the creation transaction. After inspecting the first dataset, we can extend collection to those discovered accounts before drawing final rejection rules.

No live trading, wallet signing, or transaction submission is performed.
