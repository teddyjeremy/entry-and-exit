"""Private API shell for the paper engine. No wallet signing or transaction submission."""
from __future__ import annotations
import os, time
from typing import Any
from fastapi import FastAPI, Header, HTTPException
from google.cloud import firestore

app=FastAPI(title="Entry & Exit Paper Engine",version="0.1.0")
db=firestore.Client()
COL="paper_live"

def require_token(value:str|None):
    expected=os.environ.get("DASHBOARD_API_TOKEN","")
    if not expected or value != f"Bearer {expected}":
        raise HTTPException(401,"Unauthorized")

def doc(name): return db.collection(COL).document(name)
def get_doc(name):
    snap=doc(name).get()
    return snap.to_dict() if snap.exists else {}

@app.get("/healthz")
def health():
    return {"ok":True,"mode":"PAPER_ONLY","timestamp":time.time()}

@app.get("/api/snapshot")
def snapshot(authorization:str|None=Header(default=None)):
    require_token(authorization)
    state=get_doc("state")
    return {"mode":"PAPER_ONLY","engine":state.get("engine","WAITING_FOR_FEED_ADAPTER"),
        "feed":state.get("feed","NOT_CONFIGURED"),"last_event_at":state.get("last_event_at"),
        "equity_usd":state.get("equity_usd",8.0),"realized_pnl_usd":state.get("realized_pnl_usd",0.0),
        "unrealized_pnl_usd":state.get("unrealized_pnl_usd",0.0),"open_positions":state.get("open_positions",[]),
        "watchlist":state.get("watchlist",[]),"migration_count":state.get("migration_count",0),
        "last_error":state.get("last_error"),"rules_version":"original-v1"}

@app.get("/api/trades")
def trades(authorization:str|None=Header(default=None),limit:int=100):
    require_token(authorization)
    docs=db.collection(COL).document("trades").collection("items").order_by(
        "created_at",direction=firestore.Query.DESCENDING).limit(min(limit,500)).stream()
    return [d.to_dict() for d in docs]

@app.get("/api/events")
def events(authorization:str|None=Header(default=None),limit:int=100):
    require_token(authorization)
    docs=db.collection(COL).document("events").collection("items").order_by(
        "timestamp",direction=firestore.Query.DESCENDING).limit(min(limit,500)).stream()
    return [d.to_dict() for d in docs]

@app.post("/api/control/pause")
def pause(authorization:str|None=Header(default=None)):
    require_token(authorization)
    doc("state").set({"paused":True,"engine":"PAUSED"},merge=True)
    return {"paused":True}

@app.post("/api/control/resume")
def resume(authorization:str|None=Header(default=None)):
    require_token(authorization)
    doc("state").set({"paused":False,"engine":"WAITING_FOR_FEED_ADAPTER"},merge=True)
    return {"paused":False}

@app.post("/internal/ingest")
def ingest(payload:dict[str,Any],authorization:str|None=Header(default=None)):
    """Accepts normalized, verified events from the feed adapter; idempotent by signature."""
    require_token(authorization)
    if os.environ.get("PAPER_MODE","true").lower()!="true":
        raise HTTPException(403,"Paper mode is mandatory")
    if payload.get("kind") not in {"trade","migration","health"}:
        raise HTTPException(400,"Unsupported event kind")
    event_id=payload.get("signature") or payload.get("event_id")
    if not event_id: raise HTTPException(400,"Missing idempotency key")
    ref=db.collection(COL).document("events").collection("items").document(str(event_id))
    if ref.get().exists: return {"accepted":True,"duplicate":True}
    ref.set({**payload,"received_at":time.time()})
    doc("state").set({"last_event_at":time.time(),"feed":"CONNECTED"},merge=True)
    return {"accepted":True,"duplicate":False}
