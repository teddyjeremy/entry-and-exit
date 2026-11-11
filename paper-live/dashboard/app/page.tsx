"use client";
import {useEffect,useState} from "react";
type Snapshot={configured?:boolean;mode?:string;engine?:string;feed?:string;last_event_at?:number;equity_usd?:number;realized_pnl_usd?:number;unrealized_pnl_usd?:number;open_positions?:any[];watchlist?:any[];migration_count?:number;last_error?:string;error?:string};
const money=(n?:number)=>typeof n==="number"?"$"+n.toFixed(2):"—";
export default function Home(){
 const [s,setS]=useState<Snapshot>({}); const [err,setErr]=useState("");
 async function load(){try{const r=await fetch("/api/snapshot",{cache:"no-store"});const j=await r.json();setS(j);setErr(r.ok?"":j.error||"Backend unavailable")}catch(e){setErr("Cannot reach paper engine")}}
 useEffect(()=>{load();const t=setInterval(load,3000);return()=>clearInterval(t)},[]);
 return <main>
  <div className="top"><div><div className="muted">ENTRY & EXIT / SOLANA</div><h1 style={{margin:"8px 0"}}>Paper trading control room</h1><div className="muted">Original strategy · no wallet signing · no live orders</div></div><span className="pill">PAPER ONLY</span></div>
  <div className="grid">
   <div className="card"><div className="label">Paper equity</div><div className="value">{money(s.equity_usd)}</div></div>
   <div className="card"><div className="label">Realized P&L</div><div className="value">{money(s.realized_pnl_usd)}</div></div>
   <div className="card"><div className="label">Unrealized P&L</div><div className="value">{money(s.unrealized_pnl_usd)}</div></div>
   <div className="card"><div className="label">Open positions</div><div className="value">{s.open_positions?.length??"—"}</div></div>
  </div>
  <div className="grid">
   <div className="card"><div className="label">Engine</div><div className="value" style={{fontSize:20}}>{s.engine||"NOT CONNECTED"}</div></div>
   <div className="card"><div className="label">Market feed</div><div className="value" style={{fontSize:20}}>{s.feed||"UNKNOWN"}</div></div>
   <div className="card"><div className="label">Migrated positions</div><div className="value">{s.migration_count??0}</div></div>
   <div className="card"><div className="label">Strategy</div><div className="value" style={{fontSize:18}}>Original v1</div></div>
  </div>
  {err&&<div className="card warn">{err}</div>}
  <section className="section"><h2>Open positions</h2><div className="card">{(s.open_positions||[]).length===0?<p className="muted">No open paper positions yet.</p>:(s.open_positions||[]).map((p:any)=><div className="row" key={p.mint}><div><b>{p.symbol||p.mint}</b><div className="muted">{p.mint}</div></div><div>{p.market||"BONDING_CURVE"} · {p.pnl_pct??"—"}%</div><div>Stop {p.active_stop_price??"—"}</div></div>)}</div></section>
  <section className="section"><h2>Watchlist & rejected candidates</h2><div className="card">{(s.watchlist||[]).length===0?<p className="muted">No candidates received from the engine.</p>:(s.watchlist||[]).map((p:any)=><div className="row" key={p.mint}><div><b>{p.symbol||p.mint}</b><div className="muted">{p.mint}</div></div><span className="warn">{p.reason||p.status||"WATCH"}</span></div>)}</div></section>
  <section className="section"><h2>Safety status</h2><div className="card"><p>Migration does not close a position. There is no holding-time cap.</p><p>Entry requires all original flow, wallet-safety and execution-cost checks. Missing evidence is WATCH.</p><p className="muted">Last event: {s.last_event_at?new Date(s.last_event_at*1000).toLocaleString():"No events received"}</p>{s.last_error&&<p className="bad">{s.last_error}</p>}</div></section>
  <p className="muted" style={{marginTop:32,fontSize:12}}>Refreshes every 3 seconds. All trades are simulated; no transaction is sent to Solana.</p>
 </main>
}
