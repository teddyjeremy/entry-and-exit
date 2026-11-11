# First-pass coin cohort review — 2026-11-10 00:00 UTC

## Scope and evidence

- 1,614 Pump.fun launches were observed in the hour.
- 389 passed the first-pass screen and have complete mint + bonding-curve histories for launch through launch + 3,600 seconds.
- 1,225 were not deep-collected by this screen.
- The decoder produced 29,833 BUY-side events, 26,011 SELL-side events, 56,094 curve-state observations, and 5,773 unclassified wallet flows.
- The decoded event totals are provisional evidence, not canonical Pump.fun swaps, notional, realized PnL, or a trading signal.

## Findings from the 389 analysed coins

### 1. The first-pass buyer threshold admits many marginal launches

Initial-screen buyer count in the first 10 seconds:
- 304 / 389 (78.1%) had 5–9 buyers.
- 69 / 389 (17.7%) had 10–19 buyers.
- 16 / 389 (4.1%) had 20+ buyers.
- Median was 6 buyers; 90th percentile was 13.

Across the decoded first hour, median unique buyers were 13 (25th percentile 8; 75th percentile 22). 130 / 389 coins had fewer than 10 unique buyers over the full hour.

**Interpretation:** the current minimum of 5 first-10-second buyers is a broad data-collection gate, not a selective entry rule. Do not raise it blindly yet; compare each threshold against independently measured price outcomes and execution costs.

### 2. Decoded buy volume is highly concentrated

The current concentration fields measure each wallet's share of aggregate decoded token amount bought (not share of buyer count):
- 191 / 389 coins had a top-one buyer share above 50%.
- 280 / 389 had top-five buyer share above 80%.
- 202 / 389 had top-five buyer share above 90%.
- Median top-five share was about 90.3%.

**Interpretation:** concentration is a promising risk feature, but the current field is token-volume concentration, not independent-wallet concentration. It may be affected by decoder classification and wallet relationships. Add count-based concentration and linked-wallet clustering before setting a hard cutoff.

### 3. Creator selling is common and needs timing/amount analysis

- 368 / 389 creator wallets had at least one decoded SELL event.
- 66 had at least three; 28 had at least five.
- Median creator SELL event count was 1.

**Interpretation:** a creator SELL count alone is not enough to reject a coin. We need first creator sell delay, fraction of creator-acquired tokens sold, sell size, whether selling precedes or follows broader demand, and linked creator wallets. Current native balance deltas must not be treated as proceeds.

### 4. Data-quality flags need to be first-class

- 30 / 389 coins had unclassified wallet-flow counts above 25% of their transaction count.
- 41 / 389 had a mismatch between the initial screen's first-10-second buyer count and the decoder's reconstructed count.
- 153 / 389 had more decoded SELL events than BUY events.

**Interpretation:** these are not automatically bad coins. They are signals to audit the decoder and avoid ranking on noisy metrics. Reconcile the two first-10-second counting methods and report the difference. Keep unclassified activity visible.

## Important limitations

1. The decoder infers trade side from direct curve transfers or signed token/native balance deltas; it does not decode Pump.fun instruction bytes.
2. Native wallet deltas can include fees, tips, rent, and unrelated transfers. They are not trade notional or proceeds.
3. Token amount bought/sold is gross decoded transfer volume and can exceed supply after repeated trading.
4. Curve-state values are relative balance deltas, not reconstructed absolute reserves or reliable execution prices.
5. The cohort currently has no trusted outcome label such as peak return, time-to-peak, drawdown, migration result, or executable net PnL. Therefore it is not yet possible to call any coin a winner/loser or claim a rule is profitable.
6. Wallet metrics and trade events are large JSONL files. Use Git blob retrieval or bounded/sharded outputs when auditing; the Contents API wrapper may return an empty content field for large files even though the blob exists.

## Improvements required, in priority order

### P0 — Make decoded trade evidence auditable
- Decode Pump.fun buy/sell instructions and relevant inner instructions, rather than relying on native-delta sign as a trade-side fallback.
- Preserve the classification method and confidence per event in all downstream summaries.
- Detect transactions containing multiple target-mint movements for the same wallet; do not let a last-write-wins direct-side map silently choose a side.
- Add reconciliation checks between token balance deltas, token transfers, and curve reserve movements.
- Add tests for missing token-balance changes, fee-payer effects, rent/tip transfers, multiple transfers in one transaction, and ambiguous swap routes.

### P1 — Add time-resolved wallet behaviour
- Add first/last BUY and first/last SELL timestamps per wallet.
- Add creator first-sell delay, creator token amount acquired/sold, and sell fraction where instruction evidence supports it.
- Add rolling 10s/30s/60s buyer counts, seller counts, buy/sell event counts, and net flow.
- Add count-based top-1/top-5 buyer shares alongside token-volume concentration.
- Track repeat buyers and the fraction of early buyers who become sellers within 30s, 60s, and 5m.

### P2 — Add outcomes before tuning thresholds
- Collect historical curve state / migration / post-migration price data sufficient to calculate peak return, drawdown, and time-to-peak.
- Build a quote-based execution simulator with realistic buy/sell fees, priority fees, slippage, and price impact for the intended small order sizes.
- Label outcomes without using future information in entry features.
- Compare candidate filters on a time-separated holdout cohort; report sample size, win rate, median net return, tail loss, and confidence intervals.

### P3 — Wallet relationship analysis
- Build funding-source and common-funder links, shared fee-payer patterns, and coordinated timing clusters.
- Do not equate multiple wallet addresses with independent buyers until these links are evaluated.

## Recommendation

Keep the current 5-buyer / 20%-bundle screen as a **collection filter only** for now. Do not promote it to a live entry rule. First fix/validate event classification and add time-resolved wallet/creator metrics, then collect outcome and execution labels. Only after that should we compare stricter early-buyer and concentration thresholds.
