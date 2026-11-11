# Raw Helius transaction audit — 11 November 2026

## Scope and input

This audit inspected the checked-in TRENCHER (BXwgus8w5NPgxxWxTUUHiKUz3Jezn8RB6uqowcJxpump) bonding-curve history under:

- data/candidate_coin_bxwgus/asset.json
- data/candidate_coin_bxwgus/bonding_curve/checkpoint.json
- data/candidate_coin_bxwgus/bonding_curve/transactions/page-*.jsonl

The checkpoint identifies bonding-curve address AzoTQt6G3J6J1i1dGXHuAmiVgGN9r58PUmuKbYRAfrhK. The ten stored pages contain 1,000 records and 998 distinct signatures (two duplicate signatures across pages). This is a partial collection: checkpoint completed is false. Counts below describe only these stored pages, not the token's complete history.

## Findings

- Helius source and type are not reliable swap classifiers. In this partial history, target-mint transfers occur in records labelled TRANSFER, SWAP, UNKNOWN, INITIALIZE_ACCOUNT, CREATE, and CREATE_POOL.
- Router labels cannot be used to reject a transaction. The stored history includes Jupiter- and OKX-labelled records whose nested instructions invoke the Pump program.
- A Pump program ID appearing somewhere in a transaction is not sufficient evidence of a swap. The instruction discriminator and the instruction's own account list must be inspected.
- A target-mint transfer alone is not sufficient evidence either: create, account initialization, migration, and ordinary transfer activity are present in the same address history.
- Wallet-level SOL deltas are unsuitable for trade sizing because fees, rent, tips, and unrelated transfers can be mixed into the same transaction.

## Parser boundary

strategy/helius_parser.py is intentionally an evidence parser, not a complete historical trade parser. It currently recognizes only the reviewed buyV2 and sellV2 discriminators from the Pump public IDL, and only when the same Pump instruction contains both the configured mint and bonding-curve address. It recursively examines nested Helius instructions, so router-wrapped calls can be found without trusting the router label.

Unknown discriminators—including legacy instructions present in the collected history—remain unclassified. The parser does not estimate SOL amounts, token amounts, market cap, reserves, volume, fees, slippage, or P&L. It does not infer a buy or sell from transfers. It must not be used as the historical replay parser until legacy instruction variants and quote-asset accounting are implemented and validated.

## Required next validation

1. Pin and review the historical Pump IDL variants that match the stored transactions.
2. Decode all supported Pump instruction variants and verify their account layouts against real transactions.
3. Reconcile instruction direction with target-mint and quote-asset balance changes, including Token and Token-2022.
4. Add fixtures for direct curve swaps, Jupiter/OKX-wrapped swaps, non-swap Pump instructions, PumpSwap/migration, failed transactions, duplicate signatures, and malformed records.
5. Only then calculate point-in-time trade sizes and build deterministic replay.

No trading, signing, or wallet integration is implemented by this audit.
