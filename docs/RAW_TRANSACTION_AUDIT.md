# Raw Helius transaction audit — 11 November 2026

## Scope and input

This audit inspected the checked-in TRENCHER (BXwgus8w5NPgxxWxTUUHiKUz3Jezn8RB6uqowcJxpump) bonding-curve history under:

- `data/candidate_coin_bxwgus/asset.json`
- `data/candidate_coin_bxwgus/bonding_curve/checkpoint.json`
- `data/candidate_coin_bxwgus/bonding_curve/transactions/page-*.jsonl`

The checkpoint identifies bonding-curve address `AzoTQt6G3J6J1i1dGXHuAmiVgGN9r58PUmuKbYRAfrhK`. The ten stored pages contain 1,000 records and 998 distinct signatures (two duplicate records across pages). This is a partial collection: checkpoint `completed` is false. Counts below describe only these stored pages, not the token's complete history.

## Findings

- Helius source and type are not reliable swap classifiers. In this partial history, target-mint transactions appear under several Helius types and sources.
- Router labels cannot be used to reject a transaction. Nested instructions can invoke Pump even when the outer source/type describes a router or a transfer.
- A Pump program ID appearing somewhere in a transaction is not sufficient evidence of a swap. The instruction discriminator and the instruction's own account list must be inspected.
- A target-mint transfer alone is not sufficient evidence either: create, account initialization, migration, fee operations, and ordinary transfer activity are present in the same address history.
- Wallet-level SOL deltas are unsuitable for trade sizing because fees, rent, tips, and unrelated transfers can be mixed into the same transaction.
- The token uses Token-2022 in the observed trade instructions; a complete amount parser must account for Token and Token-2022 transfer/balance evidence.

## IDL evidence and observed trade variants

The parser's original buyV2/sellV2-only allowlist was incomplete. We pinned two public Pump IDL snapshots in `docs/PUMP_IDL_MANIFEST.json`:

- 2026-09-29 snapshot `cb188ce08b5069196eef1f3e4a0c43b70099793b` (blob `2f1c65d4ff209d0f233c0e95552dd82873e4afb5`) contains legacy `buy`/`sell` and `buy_v2`/`sell_v2`.
- 2026-10-13 snapshot `639b87fb45c3adeffa6f7c4a1bf0cb85e392bf22` (blob `bb79d04e5a4ef8b286d67511757c23a15672ef51`) additionally documents `buy_v3`, `sell_v3`, `buy_exact_sol_in`, `buy_exact_quote_in_v2`, and `buy_exact_quote_in_v3`.

Scanning the ten stored pages against that IDL found 976 matching Pump swap instructions across 974 distinct signatures:

| Instruction | Matching instructions |
|---|---:|
| `buy_exact_quote_in_v3` | 350 |
| `sell_v3` | 270 |
| `buy_exact_quote_in_v2` | 144 |
| `sell_v2` | 80 |
| `buy_v3` | 63 |
| `sell` | 38 |
| `buy` | 16 |
| `buy_exact_sol_in` | 13 |
| `buy_v2` | 2 |
| **Total** | **976** |

The first observed `migrate_v2` instruction for this configured curve is in slot `468026736` (timestamp `1794379363`); a second migration instruction appears in slot `468026738`. All 976 matching trade instructions in these ten pages occur in slots **before** slot `468026736`; none were found in that slot or later. This is a slot-based comparison, not a timestamp-only guess. The 976 count is an instruction count, not necessarily a one-instruction-per-trade count, and no amounts or P&L were calculated.

The scan deduplicated transaction signatures for the distinct-signature count. The two duplicate page records remain present in the raw collection. The ten pages include later post-migration activity, but the Pump bonding-curve trade instructions identified above are all before the first observed migration slot.

## Parser boundary

`strategy/helius_parser.py` now recognizes the nine instruction variants listed in the pinned manifest, but only when the same Pump instruction contains both the configured mint and bonding-curve address. The regression suite includes minimized real Helius instruction samples from TRENCHER for all nine variants, including cases labelled `TRANSFER` / `SYSTEM_PROGRAM`.

The parser now also checks exact mint/curve/user account positions from the pinned IDL. A separate balance-evidence helper reconciles the trader and curve base-token balance deltas for real buy/sell samples. In the buy sample, trader and curve deltas match at 23,836,088,739 raw units (6 decimals); the sell sample matches at 447,727,370,313 raw units. Native SOL balance changes also sum to the negative network fee for both samples. The helper reports curve and trader SOL deltas separately and does not infer a single gross quote amount from wallet deltas or incomplete nativeTransfers. It does not calculate price, volume, fees by category, slippage, or P&L. The IDL commit dates are documentation snapshot dates, not verified on-chain activation slots. Unknown instructions remain unclassified. Do not use this parser alone for historical replay.

## Amount reconciliation sample findings

Two real Helius transactions were reduced into fixtures under `tests/fixtures/trencher_amount_samples.json`:

- Buy, `buy_exact_quote_in_v3`, slot 468026734: trader received 23,836.088739 tokens; curve token balance decreased by the same raw amount. A 9,900,000-lamport transfer from trader to curve was observed; the curve's net native balance increase was 9,853,556 lamports, while the trader's total native balance change was -10,205,000 lamports. The transaction fee was 18,449 lamports. These are distinct balance/transfer facts, not interchangeable estimates of one trade amount.
- Sell, `sell_v3`, slot 468026733: trader sold 447,727.370313 tokens; the curve token balance increased by the same raw amount. Curve native balance change was -181,707,219 lamports and trader native balance change was +177,879,387 lamports; transaction fee was 149,608 lamports. Helius did not expose a direct curve-to-trader transfer in its `nativeTransfers` array for this sample, so that array alone is not sufficient to calculate proceeds.

For both samples, the sum of all Helius account-level native balance changes equals the negative transaction fee. The new `strategy/helius_amounts.py` helper verifies base-token balance reconciliation and reports quote-side balance evidence separately. It deliberately does not claim gross quote volume, price, or P&L.

## Required next validation

1. Reconcile instruction direction with target-mint and quote-asset balance changes, including Token and Token-2022.
2. Validate exact trade amounts and fee components against raw transaction balance changes and Pump events.
3. Add fixtures for PumpSwap/migration, failed transactions, duplicate signatures, and malformed records.
4. Build a deterministic point-in-time parser only after amount reconciliation is independently validated.

No trading, signing, or wallet integration is implemented by this audit.
