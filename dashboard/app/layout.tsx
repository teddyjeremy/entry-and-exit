import './globals.css';
import type { ReactNode } from 'react';
export const metadata = { title: 'Pump Paper Desk', description: 'Strict-rule Solana paper trading monitor' };
export default function RootLayout({ children }: { children: ReactNode }) { return <html lang="en"><body>{children}</body></html>; }
