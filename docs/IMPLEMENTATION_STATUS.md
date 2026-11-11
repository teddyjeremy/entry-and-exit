# Implementation status and release gates

## Current repository scope

This repository is a read-only Helius research collector. It is not a trading bot, does not sign transactions, and does not submit swaps. The recommended thresholds are recorded in `config/strategy_baseline.json` for later replay and paper-engine work.

## Implemented in this branch

- Redact the configured Helius API key from exception text before printing or persisting it.
- Treat a short history page as provisional; mark a history complete only after a subsequent empty page confirms the end.
- Reject a missing transaction signature before writing a page or advancing the checkpoint.
- Reject a repeated pagination cursor to prevent silently duplicating a page.
- Add regression tests for secret redaction, short-page completion, repeated cursors, missing signatures, migrated tokens, non-Pump.fun curves, unknown market state, stale quotes/data, missing fields, and threshold failures.
- Add a fail-closed eligibility preflight function; missing evidence and migrated/non-Pump.fun states cannot be approved.
- Run those tests in a separate GitHub Actions workflow.
- Record the agreed recommended filter baseline as paper-only configuration. Live trading remains disabled.

## Next implementation phases

### 1. Collector correctness

- CI regression workflow passed on this branch (run `43000016702`; 4 tests passed).
- Add fixtures from real Helius responses, including rate limits, malformed responses, empty pages, and pagination boundaries.
- Add duplicate-signature detection across pages and an explicit collection manifest with per-address completion state.
- Extend collection to all required launch and bonding-curve accounts before using the data for wallet-flow conclusions.
- Preserve raw source records; keep derived classifications in separate versioned outputs.

### 2. Historical replay and strategy validation

- Build a deterministic parser for finalized Pump.fun bonding-curve swaps.
- Identify the underlying program and curve accounts; do not classify a trade solely by the router (Jupiter/OKX/etc.).
- Exclude post-migration activity from the bonding-curve strategy.
- Compute real curve SOL reserves separately from virtual reserves.
- Calculate rolling 30-second volume and unique buyers from deduplicated swap events.
- Use point-in-time data only: no future data, no survivorship bias, and no using end-of-token metadata as if it were known at entry.
- Simulate $1 buy and full-position sell quotes, protocol/network/priority fees, price impact, failed transactions, and delayed fills.
- Report eligible tokens, rejected tokens and reasons, signals, entries, exits, gross P&L, every cost, and net P&L.
- Compare the recommended profile with relaxed and strict profiles on separate train/validation periods.

### 3. Paper execution engine

- Keep live signing disabled by default and do not load a private key in paper mode.
- Use finalized/confirmed event handling with explicit slot and timestamp freshness limits.
- Make signal and order processing idempotent across reconnects and worker restarts.
- Recheck bonding-curve state and migration immediately before simulated entry.
- Require a fresh executable buy quote and a fresh sell quote for the full intended token amount.
- Reconcile simulated positions against event-derived balances and persist an append-only ledger.
- Implement hard stop, trailing stop, profit-lock, maximum hold, and emergency exit as separately tested state transitions.
- Pause entries on stale RPC data, unknown market state, incomplete evidence, or accounting mismatch.

### 4. Live execution release gate

Live execution is not authorized by this branch. Before it is even considered:

- Complete historical replay and a meaningful paper sample with realistic costs.
- Demonstrate positive net expectancy after all costs across out-of-sample periods; no guarantee of future profit.
- Pass failure-injection tests for migration races, RPC outages, duplicate events, rejected transactions, partial fills, and unavailable sell routes.
- Use a separate low-balance trading wallet, not the user's savings wallet.
- Keep signing keys in a secret manager or isolated signer; never in GitHub, Vercel frontend code, or logs.
- Add hard daily loss, maximum position, maximum open-position, and manual emergency-stop limits.
- Reconcile on-chain balances and transaction signatures before declaring any trade closed.

## Baseline thresholds

See `config/strategy_baseline.json`. These are experimental research filters, not validated profitability claims.

## Release status

- Research collector: safety fixes and regression tests added in this branch; CI passed. Real-data pagination fixtures and broader collector validation remain.
- Eligibility preflight: implemented as a pure fail-closed gate; it still requires a trusted parser to populate its snapshot fields.
- Historical replay: not implemented.
- Paper trading engine: not implemented.
- Live trading: disabled and not implemented.
