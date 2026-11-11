# Strict live paper-trading deployment

## Architecture
- Existing repository: `teddyjeremy/entry-and-exit`, isolated on branch `live-paper-v1`.
- Google Cloud Run: FastAPI paper-engine API.
- Firestore: durable runtime and event state.
- Vercel: Next.js dashboard, with the engine token held only in server-side environment variables.
- Strategy: original strict rules only. The experimental concentrated-flow path is excluded.
- Execution: paper-only. No wallet signer, private key, transaction builder, or transaction submission endpoint.

## Current status
The initial scaffold is committed. The API health/status endpoints and dashboard exist. The engine intentionally remains in SAFE_MODE and ingested normalized events are marked NOT_EVALUATED. It is not yet a running live paper trader.

The live Pump.fun decoder, strict signal evaluator, curve-based paper fill simulator, exit manager, and portfolio accounting still need implementation and fixture validation. This avoids repeating the earlier backtest mistake of treating wallet native-balance deltas as quote volume or reserve-price estimates as executable fills.

## Google Cloud setup
Create a Google Cloud project and enable:
- Cloud Run
- Cloud Build
- Firestore
- Artifact Registry
- IAM Credentials API
- Security Token Service API

Create a Firestore Native database. Configure Workload Identity Federation for GitHub Actions and grant:
- deploy identity: Cloud Run deploy + Cloud Build build permissions and `iam.serviceAccounts.actAs` on the runtime service account
- runtime service account: Firestore read/write only

Configure GitHub Actions secrets:
- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- `PAPER_API_TOKEN` (long random secret)
- `HELIUS_API_KEY`

Optional GitHub Actions variable:
- `GCP_REGION` (default `us-central1`)

Do not give the runtime identity permission to sign or submit Solana transactions.

## Vercel setup
A Vercel project named `pump-paper-desk` has been created with root directory `dashboard`. Set these server-side environment variables after the Cloud Run service exists:
- `PAPER_API_URL`: Cloud Run HTTPS URL
- `PAPER_API_TOKEN`: same secret configured on Cloud Run

The dashboard polls status every five seconds. It does not expose the token to the browser.

## Acceptance gates before paper entries
1. Implement a Helius Enhanced WebSocket / parsed-stream consumer with reconnect, heartbeat, signature deduplication, slot ordering and gap detection. Helius transactionSubscribe is available on Developer+ plans; standard logsSubscribe is an alternative but needs more local decoding.
2. Decode Pump.fun create/buy/sell instructions and associate each trade with mint, bonding curve, creator, wallet, slot and signature.
3. Validate the decoder against archived raw transactions and known examples; persist raw source events and parser version.
4. Build the three consecutive two-second confirmation windows from actual decoded quote amounts and distinct wallet identities. Do not substitute account-wide SOL balance changes for quote volume.
5. Reconstruct bonding-curve reserves and calculate size-aware entry/exit quotes, fees, impact and route validity.
6. Implement the original strict entry, creator/linked/cluster/holder rejection, cost, stop, trailing/profit-lock, 300-second exit and portfolio-sizing rules.
7. Use durable idempotency and position state so restarts cannot double-enter or lose an exit.
8. Run a paper-only soak test and reconcile simulated fills against independently queried quotes.

## Recommended controls
- Global kill switch and stale-feed circuit breaker.
- Data-quality gate: missing creator/cluster evidence means WATCH, never BUY.
- Immutable decision ledger: every rejection and entry records each rule's pass/fail, evidence, timestamps and parser version.
- Shared evaluator for historical replay and live mode to prevent backtest/live drift.
- Alerts for feed disconnects, stale candidates, stuck positions, stop triggers, migration and API errors.
- Daily P&L reconciliation with fees, price impact and slippage shown separately.
- Helius and Google Cloud budget alerts and usage caps.
