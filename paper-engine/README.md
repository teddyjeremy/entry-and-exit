# Live paper engine (strict strategy)

This service is the Cloud Run API and durable state boundary for the paper trader.

## Safety defaults

- Paper-only. There is no wallet key, signer, transaction builder, or transaction submission path.
- Strategy mode is permanently labelled `ORIGINAL_STRICT`; the experimental concentrated-flow path is not implemented.
- API writes require `PAPER_API_TOKEN`.
- The service starts in `SAFE_MODE`. It does not create BUY decisions until a verified Pump.fun decoder and live event adapter have passed fixtures.
- Raw Helius notifications must not be posted directly to `/internal/market-events`. Only a validated adapter may produce the normalized schema.

## Deploy

Build and deploy this directory to Cloud Run using the repository workflow. Configure:
- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- `PAPER_API_TOKEN`
- `HELIUS_API_KEY`

Grant the runtime service account Firestore read/write access. Create a Firestore Native database in the same project/region before first deployment.

## API

- `GET /health`: unauthenticated Cloud Run health check.
- `GET /v1/status`: authenticated dashboard status.
- `POST /internal/market-events`: authenticated normalized-event ingestion; currently stores events as NOT_EVALUATED.
- `GET /v1/recent-events`: authenticated placeholder until an indexed retention strategy is added.

This is an infrastructure and integration scaffold, not a claim that the live strategy is trading. The live decoder, strict evaluator, paper fill simulator, and exit manager are separate acceptance gates.
