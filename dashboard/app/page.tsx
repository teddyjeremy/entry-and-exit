'use client';

import { useEffect, useState } from 'react';

type Status = {
  connected?: boolean; mode?: string; strategy?: string; engine_state?: string;
  feed_state?: string; last_event_at?: string | null; open_positions?: number;
  portfolio_value_usd?: number; real_orders_enabled?: boolean; blockers?: string[];
};

export default function Home() {
  const [status, setStatus] = useState<Status | null>(null);
  const [updated, setUpdated] = useState<string>('');
  async function refresh() {
    const response = await fetch('/api/status', { cache: 'no-store' });
    setStatus(await response.json());
    setUpdated(new Date().toLocaleTimeString());
  }
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, []);

  const connected = !!status?.connected;
  return <main className="shell">
    <header className="topbar"><div><div className="eyebrow">SOLANA · PAPER EXECUTION</div><h1>Pump Paper Desk</h1><p className="muted">Live market monitoring · original strict strategy · no wallet signing</p></div><div className="live-pill"><span /> PAPER MODE</div></header>
    <section className="notice"><strong>Safety lock active</strong><span>Real transactions are disabled. No private key or wallet signer is configured in this project.</span></section>
    <section className="grid">
      <article className="metric"><span>Engine</span><strong>{status?.engine_state ?? 'CONNECTING'}</strong><small>{connected ? 'Cloud engine reachable' : 'Waiting for backend connection'}</small></article>
      <article className="metric"><span>Market feed</span><strong>{status?.feed_state ?? 'CHECKING'}</strong><small>Must be decoder-validated before entries</small></article>
      <article className="metric"><span>Open paper positions</span><strong>{status?.open_positions ?? 0}</strong><small>Original portfolio concurrency rules</small></article>
      <article className="metric"><span>Paper portfolio</span><strong>${(status?.portfolio_value_usd ?? 1).toFixed(2)}</strong><small>Initial paper balance placeholder</small></article>
    </section>
    <section className="panel"><div className="panel-head"><div><div className="eyebrow">STRATEGY CONFIGURATION</div><h2>Original rules only</h2></div><span className="tag">STRICT</span></div>
      <div className="rule-grid"><div><b>Price formation</b><p>+20% impulse · 10–40% pullback · reclaim confirmation</p></div><div><b>Buyer confirmation</b><p>3 consecutive 2-second windows · 3 buyers per window · 5 distinct overall</p></div><div><b>Wallet concentration</b><p>Largest buyer ≤72% · creator and linked-wallet rejection checks</p></div><div><b>Risk and exits</b><p>−5% hard stop · 40% trailing distance after +10% · 300-second maximum hold</p></div></div>
    </section>
    <section className="panel"><div className="panel-head"><div><div className="eyebrow">SYSTEM HEALTH</div><h2>Readiness blockers</h2></div><span className={connected ? 'tag' : 'tag warn'}>{connected ? 'CONNECTED' : 'NOT READY'}</span></div>
      <ul className="blockers">{(status?.blockers ?? ['Connecting to the Cloud Run engine…']).map((item, i) => <li key={i}>{item}</li>)}</ul>
      <div className="foot">Last dashboard refresh: {updated || '—'} · Last market event: {status?.last_event_at ?? 'None received'}</div>
    </section>
    <footer>Research-grade paper trading only. A missing signal, stale feed, unverified wallet attribution, or unavailable exit quote must result in NO TRADE.</footer>
  </main>;
}
