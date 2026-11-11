# Original-rules live paper trader

A separate paper-only runtime alongside the existing research collector. It never loads a wallet key, signs a transaction, or submits an on-chain trade.

## Agreed strategy behaviour
- Only the original entry strategy is enabled; no concentrated-flow/relaxed path.
- First 60 seconds after launch; +20% impulse; 10–40% pullback; reclaim; three consecutive 2-second confirmation windows; >3:1 buy/sell quote volume in every window; at least 3 unique buyers per window; sellers no more than half buyers; at least 5 distinct buyers overall; largest buyer <=72%.
- Creator, linked-wallet, cluster, holder-distribution and execution-cost checks fail closed. Missing evidence means WATCH, not BUY.
- Migration is a venue transition, not an exit. An open position remains open and is monitored on PumpSwap.
- No maximum holding period.
- Exits are dynamic: hard stop, trailing/profit-lock floors, weakening buy flow, or sustained sell pressure.
- Portfolio capacity and stake scale at portfolio doublings; duplicate mints are blocked.

## Implementation status
- strategy.py contains deterministic entry/exit calculations against normalized verified trade events.
- service.py provides a Firestore-backed API shell, idempotent event ingestion and pause/resume controls.
- Dashboard source is under dashboard/.
- A production Helius feed adapter, PumpSwap decoder, executable quote verifier, creator/linked-wallet/cluster/holder evidence provider, and end-to-end tests are still required before paper positions can be opened. This is fail-closed by design; it will not invent quote volume from native balance-delta proxies.

The dynamic exit defaults (5-second windows and 60% buy-volume decay) are proposed thresholds for paper validation, not original entry rules. They are isolated in Rules and should be calibrated from replay before enabling automatic paper exits.

## Google Cloud setup
1. Create a Google Cloud project and enable billing, Cloud Run, Artifact Registry, Cloud Build, Firestore and Secret Manager.
2. Create a Firestore Native database in the same region.
3. Create service account paper-live-engine with Firestore User and Secret Manager Secret Accessor roles.
4. Create Secret Manager secrets helius-api-key and paper-dashboard-token. Do not commit either value.
5. Create Artifact Registry repository paper-live.
6. Build/deploy using cloudbuild.yaml. Cloud Run is set to min=1/max=1 with CPU always allocated. It can still restart, so a future stream worker must reconnect and recover from Firestore.
7. Configure Vercel server-only environment variables PAPER_API_URL and PAPER_API_TOKEN. The token must match paper-dashboard-token.

Example:
```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com firestore.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create paper-live --repository-format=docker --location=us-central1
gcloud firestore databases create --location=us-central1 --type=firestore-native
gcloud secrets create helius-api-key --replication-policy=automatic
gcloud secrets create paper-dashboard-token --replication-policy=automatic
```

## Required before enabling paper entries
- Implement/test Helius logsSubscribe plus Enhanced Transactions decoding for Pump.fun create/buy/sell and PumpSwap swaps.
- Verify exact quote SOL and token amounts from matched transfers, not nativeBalanceChange proxies.
- Decode bonding-curve and PumpSwap pool reserves; produce size-specific buy and exit quotes.
- Verify the current fee schedule, price impact and round-trip costs.
- Add creator/linked-wallet/cluster/holder evidence. Unknown evidence remains WATCH.
- Add replay fixtures, portfolio accounting, restart/idempotency tests, and operational alerts.

No live-order code is included.

## Vercel project
The dashboard is linked to the Vercel project entry-exit-paper-dashboard with root directory paper-live/dashboard. The project has not been deployed yet; the backend URL and token are intentionally not configured until the Cloud Run service and secrets exist.
