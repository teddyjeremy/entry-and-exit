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

## Safety tests and strategy baseline

- Run local regression tests with `python -m unittest discover -s tests -v`.
- GitHub Actions runs the same tests on pushes and pull requests.
- The agreed recommended filters are recorded in `config/strategy_baseline.json` as a paper-research baseline only.
- Collector safety changes and remaining implementation/release gates are documented in `docs/IMPLEMENTATION_STATUS.md`.

**Important:** this repository is still a read-only research collector. It does not implement the historical replay engine, paper execution engine, wallet signing, or live trading. `live_trading_enabled` remains `false` in the baseline configuration.
- A fail-closed preflight gate is available in `strategy/eligibility.py`; it rejects migrated tokens, non-Pump.fun curves, missing evidence, stale observations, unavailable quotes, and threshold failures. It is not yet connected to a transaction parser or trading engine.

## Portfolio limits and trade sizing (paper-strategy policy)

- Start with at most **one concurrent open position**.
- Increase the limit by one at each additional **$5 of realized portfolio equity**: below $5 = 1 position; $5–$9.99 = 2; $10–$14.99 = 3.
- Unrealized gains on open positions do not increase the limit.
- An open position keeps its slot until the exit is confirmed and reconciled; no new entry can use that slot before then.
- A mint can be entered **only once ever**. Exiting does not make that mint eligible again.
- Starting from the configured $2.70 portfolio and $1.00 stake, increase the stake by **50% for every full doubling** of realized equity: $2.70 → $1.00; $5.40 → $1.50; $10.80 → $2.25; $21.60 → $3.38.
- Cap each trade at **$100**, and never stake more than available realized equity. Stake tiers and concurrent-position tiers are independent.
- Pure policies are in `strategy/portfolio_rules.py`; persistent ledger and atomic reservation integration are still required in the future paper engine.
