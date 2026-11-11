"""Deterministic paper-trading rules. No wallet signing or transaction submission."""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from typing import Any

@dataclass(frozen=True)
class Rules:
    entry_seconds: int = 60
    impulse_pct: float = 20.0
    pullback_min_pct: float = 10.0
    pullback_max_pct: float = 40.0
    reclaim_pct: float = 1.0
    flow_window_seconds: int = 2
    confirmation_windows: int = 3
    min_buy_sell_ratio: float = 3.0
    min_buyers_per_window: int = 3
    max_sellers_to_buyers: float = 0.5
    min_distinct_buyers: int = 5
    max_largest_buyer_share_pct: float = 72.0
    max_entry_impact_pct: float = 2.0
    max_exit_impact_pct: float = 2.0
    max_buy_tax_pct: float = 2.0
    max_sell_tax_pct: float = 2.0
    max_round_trip_cost_pct: float = 4.0
    creator_sell_reject_supply_pct: float = 0.05
    linked_wallet_sell_reject_supply_pct: float = 0.25
    cluster_sell_reject_supply_pct: float = 0.25
    cluster_buy_volume_reject_pct: float = 35.0
    cluster_holdings_reject_pct: float = 20.0
    wallet_holdings_reject_pct: float = 20.0
    hard_stop_pct: float = 5.0
    trailing_activation_pct: float = 10.0
    trailing_giveback_pct: float = 40.0
    profit_locks: tuple = ((10.0, 5.0), (50.0, 15.0), (100.0, 40.0), (200.0, 80.0))
    # Proposed dynamic exit defaults for paper validation; not original entry rules.
    exit_flow_window_seconds: int = 5
    sell_pressure_confirmations: int = 2
    buy_decay_pct: float = 60.0
    buy_decay_window_seconds: int = 10

@dataclass
class TradeEvent:
    mint: str
    timestamp: float
    side: str
    wallet: str
    quote_sol: float
    token_amount: float
    price_sol: float
    market: str = "BONDING_CURVE"
    signature: str = ""

def _buckets(events: list[TradeEvent], launch_ts: float, width: int, until: float):
    count = max(0, int((until-launch_ts)//width)+1)
    out = [{"start":launch_ts+i*width,"buys":0.0,"sells":0.0,
            "buy_wallets":set(),"sell_wallets":set(),"wallet_buy":defaultdict(float),
            "token":0.0,"quote":0.0} for i in range(count)]
    for e in events:
        idx=int((e.timestamp-launch_ts)//width)
        if idx<0 or idx>=len(out) or e.token_amount<=0 or e.quote_sol<=0: continue
        b=out[idx]; b["token"]+=e.token_amount; b["quote"]+=e.quote_sol
        if e.side.upper()=="BUY":
            b["buys"]+=e.quote_sol; b["buy_wallets"].add(e.wallet); b["wallet_buy"][e.wallet]+=e.quote_sol
        elif e.side.upper()=="SELL":
            b["sells"]+=e.quote_sol; b["sell_wallets"].add(e.wallet)
    for b in out: b["price"]=b["quote"]/b["token"] if b["token"] else None
    return out

def evaluate_entry(events: list[TradeEvent], launch_ts: float, now: float,
                   safety: dict[str,Any], execution: dict[str,Any], rules: Rules=Rules()):
    """Return BUY only when all original rules and evidence gates pass."""
    if now-launch_ts>rules.entry_seconds: return {"decision":"NO_TRADE","reason":"ENTRY_WINDOW_EXPIRED"}
    buckets=_buckets(events,launch_ts,rules.flow_window_seconds,min(now,launch_ts+rules.entry_seconds))
    valid=[(i,b) for i,b in enumerate(buckets) if b["price"] is not None]
    if len(valid)<5: return {"decision":"WATCH","reason":"INSUFFICIENT_PRICE_HISTORY"}
    baseline=valid[0][1]["price"]
    impulse=next(((i,b) for i,b in valid if b["price"]>=baseline*(1+rules.impulse_pct/100)),None)
    if not impulse: return {"decision":"WATCH","reason":"NO_20_PERCENT_IMPULSE"}
    peak=impulse[1]["price"]; peak_i=impulse[0]; pullback=None; reclaim=None
    for i in range(peak_i+1,len(buckets)):
        p=buckets[i]["price"]
        if p is None: continue
        if pullback is None:
            if p>peak: peak,peak_i=p,i
            dd=(peak-p)/peak*100
            if rules.pullback_min_pct<=dd<=rules.pullback_max_pct: pullback=(i,p)
            elif dd>rules.pullback_max_pct: return {"decision":"WATCH","reason":"PULLBACK_EXCEEDED_40_PERCENT"}
        else:
            low_i,low_p=pullback; low_p=min(low_p,p); pullback=(low_i,low_p)
            if (peak-low_p)/peak*100>rules.pullback_max_pct: return {"decision":"WATCH","reason":"PULLBACK_EXCEEDED_40_PERCENT"}
            bucket_time=buckets[i]["start"]
            prior_prices=[e.price_sol for e in events if bucket_time-5.0<=e.timestamp<bucket_time and e.price_sol>0]
            previous_5s_high=max(prior_prices) if prior_prices else peak
            if p>=previous_5s_high*(1+rules.reclaim_pct/100): reclaim=i; break
    if pullback is None: return {"decision":"WATCH","reason":"NO_10_TO_40_PERCENT_PULLBACK"}
    if reclaim is None: return {"decision":"WATCH","reason":"NO_RECLAIM_ABOVE_PREVIOUS_5S_HIGH"}
    flow=buckets[reclaim+1:reclaim+1+rules.confirmation_windows]
    if len(flow)!=rules.confirmation_windows or any(x["price"] is None for x in flow):
        return {"decision":"WATCH","reason":"THREE_CONFIRMATION_WINDOWS_NOT_COMPLETE"}
    # The confirmation is the completed third flow window; it must be fresh,
    # then the next observation must still hold the reclaim level.
    confirmation_end=buckets[reclaim+rules.confirmation_windows]["start"]+rules.flow_window_seconds
    age=now-confirmation_end
    if not 1.0<=age<=2.0:
        return {"decision":"WATCH","reason":"CONFIRMATION_NOT_1_TO_2_SECONDS_OLD","confirmation_age_seconds":age}
    reclaim_time=buckets[reclaim]["start"]
    prior=[e.price_sol for e in events if reclaim_time-5.0<=e.timestamp<reclaim_time and e.price_sol>0]
    if not prior:
        return {"decision":"WATCH","reason":"MISSING_PREVIOUS_5S_HIGH"}
    hold_level=max(prior)*(1+rules.reclaim_pct/100)
    latest=[e for e in events if now-2.0<=e.timestamp<=now]
    if not latest or max(e.price_sol for e in latest)<hold_level:
        return {"decision":"WATCH","reason":"NEXT_OBSERVATION_FAILED_RECLAIM_RECHECK"}
    buyers=set(); wallet_buy=defaultdict(float); total_buy=0.0; checks=[]
    for n,b in enumerate(flow,1):
        ratio=b["buys"]/b["sells"] if b["sells"] else (float("inf") if b["buys"] else 0.0)
        nb,ns=len(b["buy_wallets"]),len(b["sell_wallets"])
        passed=ratio>rules.min_buy_sell_ratio and nb>=rules.min_buyers_per_window and ns<=nb*rules.max_sellers_to_buyers
        checks.append({"window":n,"buy_sol":b["buys"],"sell_sol":b["sells"],"ratio":None if ratio==float("inf") else ratio,"buyers":nb,"sellers":ns,"passed":passed})
        if not passed: return {"decision":"WATCH","reason":"FLOW_CONFIRMATION_FAILED","windows":checks}
        buyers|=b["buy_wallets"]; total_buy+=b["buys"]
        for w,v in b["wallet_buy"].items(): wallet_buy[w]+=v
    largest=max(wallet_buy.values(),default=0.0)/total_buy*100 if total_buy else 100.0
    if len(buyers)<rules.min_distinct_buyers: return {"decision":"WATCH","reason":"FEWER_THAN_FIVE_DISTINCT_BUYERS","distinct_buyers":len(buyers)}
    if largest>rules.max_largest_buyer_share_pct: return {"decision":"WATCH","reason":"LARGEST_BUYER_SHARE_EXCEEDED","largest_buyer_share_pct":largest}
    required=("creator_check","linked_wallet_check","cluster_check","holder_check")
    missing=[k for k in required if safety.get(k)!="PASS"]
    if missing: return {"decision":"WATCH","reason":"SAFETY_EVIDENCE_NOT_PASSED","missing_or_failed":missing}
    rejects=(("creator_sell_supply_pct",rules.creator_sell_reject_supply_pct),
      ("linked_wallet_sell_supply_pct",rules.linked_wallet_sell_reject_supply_pct),
      ("cluster_sell_supply_pct",rules.cluster_sell_reject_supply_pct),
      ("cluster_buy_volume_pct",rules.cluster_buy_volume_reject_pct),
      ("cluster_holdings_pct",rules.cluster_holdings_reject_pct),
      ("largest_wallet_holdings_pct",rules.wallet_holdings_reject_pct))
    for key,limit in rejects:
        if safety.get(key) is None: return {"decision":"WATCH","reason":"SAFETY_METRIC_MISSING","field":key}
        if float(safety[key])>limit: return {"decision":"REJECT","reason":"SAFETY_THRESHOLD","field":key,"value":safety[key],"limit":limit}
    if execution.get("verified") is not True: return {"decision":"WATCH","reason":"EXECUTION_QUOTE_NOT_VERIFIED"}
    limits={"entry_impact_pct":rules.max_entry_impact_pct,"exit_impact_pct":rules.max_exit_impact_pct,
      "buy_tax_pct":rules.max_buy_tax_pct,"sell_tax_pct":rules.max_sell_tax_pct,"round_trip_cost_pct":rules.max_round_trip_cost_pct}
    for key,limit in limits.items():
        if execution.get(key) is None or float(execution[key])>limit:
            return {"decision":"WATCH","reason":"EXECUTION_COST_LIMIT_OR_MISSING","field":key,"limit_pct":limit}
    return {"decision":"BUY","reason":"ALL_ORIGINAL_RULES_PASSED","entry_price_sol":flow[-1]["price"],
      "distinct_buyers":len(buyers),"largest_buyer_share_pct":largest,"windows":checks}

def exit_decision(position:dict[str,Any],events:list[TradeEvent],now_price:float,now:float,
                  migration:bool=False,route_verified:bool=True,rules:Rules=Rules()):
    """Migration is not an exit; no time cap exists."""
    entry=float(position["entry_price"]); peak=max(float(position.get("peak_price",entry)),now_price)
    pnl=(now_price/entry-1)*100; stop=entry*(1-rules.hard_stop_pct/100)
    if peak>=entry*(1+rules.trailing_activation_pct/100): stop=max(stop,peak*(1-rules.trailing_giveback_pct/100))
    for reached,locked in rules.profit_locks:
        if peak>=entry*(1+reached/100): stop=max(stop,entry*(1+locked/100))
    if migration:
        position["market"]="PUMPSWAP"; position["migrated_at"]=position.get("migrated_at") or now
    position["peak_price"]=peak; position["active_stop_price"]=stop
    reason=None
    if now_price<=stop: reason="TRAILING_STOP" if stop>entry*(1-rules.hard_stop_pct/100) else "HARD_STOP"
    else:
        width=rules.exit_flow_window_seconds
        pressure_windows=[]
        for n in range(rules.sell_pressure_confirmations):
            start=now-(n+1)*width
            end=now-n*width
            window=[e for e in events if start<=e.timestamp<end]
            b=sum(e.quote_sol for e in window if e.side.upper()=="BUY")
            s=sum(e.quote_sol for e in window if e.side.upper()=="SELL")
            pressure_windows.append(s>b and s>0)
        if len(pressure_windows)==rules.sell_pressure_confirmations and all(pressure_windows):
            reason="SUSTAINED_SELL_PRESSURE"
        else:
            span=rules.buy_decay_window_seconds
            current=[e for e in events if now-span<=e.timestamp<=now]
            previous=[e for e in events if now-2*span<=e.timestamp<now-span]
            current_buy=sum(e.quote_sol for e in current if e.side.upper()=="BUY")
            current_sell=sum(e.quote_sol for e in current if e.side.upper()=="SELL")
            previous_buy=sum(e.quote_sol for e in previous if e.side.upper()=="BUY")
            decay=(1-current_buy/previous_buy)*100 if previous_buy>0 else 0
            if previous_buy>0 and decay>=rules.buy_decay_pct and current_sell>=current_buy:
                reason="BUY_VOLUME_DECAY_WITH_SELL_PRESSURE"
    if reason and not route_verified:
        return {"action":"HOLD_ROUTE_UNAVAILABLE","reason":reason,"pnl_pct":pnl,"active_stop_price":stop,"peak_price":peak}
    if reason: return {"action":"SELL","reason":reason,"pnl_pct":pnl,"active_stop_price":stop,"peak_price":peak}
    return {"action":"HOLD","reason":"NO_EXIT_SIGNAL","pnl_pct":pnl,"active_stop_price":stop,"peak_price":peak,"migration_continues_position":bool(migration)}

def portfolio_limits(equity:float,base_equity:float,base_stake:float=1.0):
    import math
    doublings=max(0,math.floor(math.log2(equity/base_equity))) if equity>=base_equity else 0
    return {"max_open_positions":1+doublings,"stake_usd":min(100.0,base_stake*(1.5**doublings))}
