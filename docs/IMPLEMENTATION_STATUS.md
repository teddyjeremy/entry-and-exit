# Implementation status and release gates

## Current repository scope

This repository is a read-only Helius research collector. It is not a trading bot, does not sign transactions, and does not submit swaps. The recommended thresholds are recorded in `config/strategy_baseline.json` for later replay and paper-engine work.

## Implemented in this branch

- Redact the configured Helius API key from exception text before printing or persisting metadata errors.
- Treat a short history page as provisional; mark a history complete only after a subsequent empty page confirms the end.
- Reject a missing transaction signature before writing a page or advancing the checkpoint.
- Reject a repeated pagination cursor to prevent silently duplicating a page.
- Add regression tests for secret redaction, short-page completion, repeated cursors, missing signatures, migrated tokens, non-Pump.fun curves, unknown market state, stale quotes/data, missing fields, and threshold failures.
- Add a fail-closed eligibility preflight function; missing evidence and migrated/non-Pump.fun states cannot be approved.
- Run those tests in a separate GitHub Actions workflow.
- Add a conservative Helius Pump instruction evidence parser that recursively inspects nested router calls and recognizes nine IDL-pinned trade variants (legacy buy/sell, v2, v3, and exact-input buys) only when mint and curve occupy their exact IDL account positions; expose the trader and quote mint from the same layout.
- Add a raw-transaction audit documenting the TRENCHER sample's mixed Helius labels, duplicate signatures, incomplete collection, and parser limitations.
- Add parser regression tests using real TRENCHER Helius instruction samples for all nine supported variants, plus a pinned Pump IDL manifest and account-role layouts. The partial 1,000-record sample contains 976 matching trade instructions in 974 distinct signatures, all in slots before the first observed migration slot; this is not a complete token history.
- Add a balance-evidence helper that reconciles trader/curve base-token balance changes from Helius accountData and separately reports SOL/quote balance evidence; real buy and sell fixtures verify token amounts and network-fee reconciliation. It does not infer trade price, gross quote volume, or P&L.
- Add portfolio admission rules: one concurrent position initially, plus one position for each $5 milestone of realized equity; a position slot is occupied until exit is confirmed.
- Enforce one entry per mint for the lifetime of the strategy, including after exit; the pure policy rejects previously traded mints.
- Add 11 portfolio-policy regression tests and store the policy in `config/strategy_baseline.json`.
- Add trade stake sizing: each full doubling of realized portfolio equity increases the stake by 50%, starting from $1 on the configured $2.70 baseline; maximum stake is $100 and cannot exceed available realized equity.
- Add regression tests for exact doubling boundaries, compounding stake tiers, equity/cap limits, and invalid sizing configuration.
- Record the agreed recommended filter baseline as paper-only configuration. Live trading remains disabled.

## Next implementation phases

### 1. Collector correctness

- CI regression workflow passed on this branch (run `43000016702`; 4 tests passed).
- Add fixtures from real Helius responses, including rate limits, malformed responses, empty pages, and pagination boundaries.
- Add duplicate-signature detection across pages and an explicit collection manifest with per-address completion state.
- Extend collection to all required launch and bonding-curve accounts before using the data for wallet-flow conclusions.
- Preserve raw source records; keep derived classifications in separate versioned outputs.

### 2. Historical replay and strategy validation

- Current parser recognizes nine IDL-pinned trade variants but is only an instruction-evidence gate, not a complete swap parser. Decode arguments and reconcile exact SOL/quote-asset and token amounts, fees, and event/balance deltas before replay.
- Build a deterministic parser for finalized Pump.fun bonding-curve swaps, including verified quote-asset/token balance reconciliation and trade-size accounting.
- Identify the underlying program and curve accounts; do not classify a trade solely by the router (Jupiter/OKX/etc.).
- Include Token and Token-2022 transfer evidence where applicable.
- Exclude post-migration activity from the bonding-curve strategy.
- Compute real curve SOL reserves separately from virtual reserves.
- Calculate rolling 30-second volume and unique buyers from deduplicated swap events.
- Use point-in-time data only: no future data, no survivorship bias, and no using end-of-token metadata as if it were known at entry.
- Simulate the configured stake-sizing tiers, $5 concurrent-position limits, $100 per-trade cap, full-position sell quotes, protocol/network/priority fees, price impact, failed transactions, and delayed fills.
- Report eligible tokens, rejected tokens and reasons, signals, entries, exits, gross P&L, every cost, and net P&L.
- Compare the recommended profile with relaxed and strict profiles on separate train/validation periods.

### 3. Paper execution engine

- Apply `strategy/portfolio_rules.py` before every entry. Use realized equity (not unrealized open-position gains) for capacity tiers; default tiers are 1 slot below $5, 2 from $5 to below $10, 3 from $10 to below $15, and so on.
- Calculate the per-trade stake using `trade_stake_usd`: 50% larger after every full doubling of realized portfolio equity, starting at $1 from the configured $2.70 baseline and capped at $100.
- Persist every mint's first-entry marker permanently in the append-only ledger. Never clear it after exit; reject any later signal for that mint.
- Reserve a free slot and mark the mint as traded atomically before order submission to prevent concurrent workers from double-entering. Release the slot only after exit confirmation and balance reconciliation.
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
- Pump instruction evidence parser: recognizes nine pinned legacy/v2/v3 Pump trade variants, validates exact IDL account roles, and has real Helius fixtures.
- Helius balance evidence: trader/curve token deltas reconcile for real buy/sell samples; quote-side evidence is kept separate and gross quote accounting, fee attribution, and P&L remain incomplete.
- Portfolio admission policy: implemented and tested as a pure gate; persistent ledger integration, atomic reservation, and exit-confirmation handling remain part of the paper engine.
- Trade stake sizing: implemented and unit-tested as a pure calculation; the future paper engine must apply it using realized equity before every entry.
- Pump IDL snapshots: pinned legacy and current public IDL revisions; commit dates are documentation snapshots, not verified on-chain activation boundaries.
- Historical replay: not implemented.
- Paper trading engine: not implemented.
- Live trading: disabled and not implemented.
