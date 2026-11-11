from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from google.cloud import firestore
from pydantic import BaseModel, Field

app = FastAPI(title="Pump Paper Engine", version="0.1.0")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT_ID")
API_TOKEN = os.getenv("PAPER_API_TOKEN", "")
COLLECTION = os.getenv("FIRESTORE_COLLECTION", "paper_engine")
db = firestore.Client(project=PROJECT_ID) if PROJECT_ID else firestore.Client()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_token(authorization: str | None) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="PAPER_API_TOKEN is not configured")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, API_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")


class NormalizedMarketEvent(BaseModel):
    """Trusted adapter output. Raw RPC transactions must never be sent as this model."""
    mint: str = Field(min_length=32, max_length=64)
    timestamp_ms: int = Field(gt=0)
    launch_timestamp_ms: int = Field(gt=0)
    price_sol: float = Field(gt=0)
    buy_quote_sol: float = Field(ge=0)
    sell_quote_sol: float = Field(ge=0)
    buyers: list[str] = []
    sellers: list[str] = []
    creator_sell_supply_pct: float | None = None
    linked_wallet_sell_supply_pct: float | None = None
    cluster_sell_supply_pct: float | None = None
    cluster_buy_volume_pct: float | None = None
    cluster_holdings_pct: float | None = None
    largest_wallet_holding_pct: float | None = None
    largest_buyer_volume_pct: float | None = None
    creator_evidence_confidence: float | None = None
    entry_impact_pct: float | None = None
    exit_impact_pct: float | None = None
    buy_tax_pct: float | None = None
    sell_tax_pct: float | None = None
    executable_exit: bool = False
    migrated: bool = False
    source_signature: str = Field(min_length=32, max_length=100)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utc_now()}


@app.get("/v1/status")
def status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    state = db.collection(COLLECTION).document("runtime").get()
    payload = state.to_dict() if state.exists else {}
    return {
        "mode": "PAPER_ONLY",
        "strategy": "ORIGINAL_STRICT",
        "engine_state": payload.get("engine_state", "SAFE_MODE"),
        "feed_state": payload.get("feed_state", "NOT_CONFIGURED"),
        "last_event_at": payload.get("last_event_at"),
        "open_positions": payload.get("open_positions", 0),
        "portfolio_value_usd": payload.get("portfolio_value_usd"),
        "real_orders_enabled": False,
        "updated_at": payload.get("updated_at"),
        "blockers": payload.get("blockers", [
            "A verified Pump.fun transaction decoder and live event adapter are not connected.",
            "No BUY decisions are permitted until the normalized event feed is validated."
        ])
    }


@app.post("/internal/market-events")
def ingest_event(event: NormalizedMarketEvent,
                 authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    # Fail closed: ingestion is deliberately separated from strategy decisions.
    # The adapter contract is versioned and auditable before the evaluator is enabled.
    event_ref = db.collection(COLLECTION).document("events").collection(event.mint).document(
        f"{event.timestamp_ms}-{event.source_signature}"
    )
    event_ref.set({**event.model_dump(), "received_at": utc_now(), "decision": "NOT_EVALUATED"})
    db.collection(COLLECTION).document("runtime").set({
        "engine_state": "SAFE_MODE",
        "feed_state": "EVENTS_RECEIVED_DECODER_UNVERIFIED",
        "last_event_at": utc_now(),
        "open_positions": 0,
        "portfolio_value_usd": None,
        "real_orders_enabled": False,
        "blockers": ["Strategy evaluation remains disabled until event-decoder fixtures pass."],
        "updated_at": utc_now()
    }, merge=True)
    return {"accepted": True, "decision": "NOT_EVALUATED", "reason": "SAFE_MODE"}


@app.get("/v1/recent-events")
def recent_events(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    docs = (db.collection(COLLECTION).document("events").collections())
    # Firestore subcollection listing is not used as a public API; dashboard reads status only.
    return {"items": [], "note": "Event browser will be enabled after retention/indexing policy is configured."}
