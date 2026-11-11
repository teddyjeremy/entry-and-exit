import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET() {
  const base = process.env.PAPER_API_URL;
  const token = process.env.PAPER_API_TOKEN;
  if (!base || !token) {
    return NextResponse.json({
      connected: false,
      mode: 'PAPER_ONLY',
      strategy: 'ORIGINAL_STRICT',
      engine_state: 'NOT_CONNECTED',
      feed_state: 'NOT_CONFIGURED',
      blockers: ['Set PAPER_API_URL and PAPER_API_TOKEN in the Vercel project environment.'],
      real_orders_enabled: false
    }, { status: 200 });
  }
  try {
    const response = await fetch(new URL('/v1/status', base), {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
      signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw new Error(`Engine returned HTTP ${response.status}`);
    return NextResponse.json({ connected: true, ...(await response.json()) });
  } catch (error) {
    return NextResponse.json({
      connected: false,
      mode: 'PAPER_ONLY',
      strategy: 'ORIGINAL_STRICT',
      engine_state: 'UNREACHABLE',
      feed_state: 'UNKNOWN',
      blockers: [error instanceof Error ? error.message : 'Engine unavailable'],
      real_orders_enabled: false
    }, { status: 200 });
  }
}
