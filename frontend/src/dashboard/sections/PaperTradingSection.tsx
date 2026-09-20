'use client';

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { usePaperTradingQuery } from '../../data/queries';
import type { PaperChampion } from '../../types';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

function ChampionCard({ champion }: { champion: PaperChampion }) {
  return (
    <div className="rounded border border-border p-3">
      <div className="mb-2 flex items-center justify-between font-mono text-xs">
        <span className="font-semibold">
          {champion.strategy_id} <span className="text-muted-foreground">({champion.family} · {champion.symbol})</span>
        </span>
        {champion.recent_findings.length > 0 && (
          <span className="rounded border border-red-500/60 px-1.5 py-0.5 text-red-600 dark:text-red-400">
            {champion.recent_findings[0].finding_type}
          </span>
        )}
      </div>
      <div className="h-40 w-full font-mono text-xs">
        {champion.equity_curve.length === 0 ? (
          <p className="py-2 text-muted-foreground">No fills yet — waiting on the first paper order.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={champion.equity_curve} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                tickFormatter={(v: string) => new Date(v).toLocaleDateString()}
              />
              <YAxis
                tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
                domain={['auto', 'auto']}
                tickFormatter={(v: number) => `€${v.toFixed(0)}`}
              />
              <Tooltip
                formatter={(value: number) => [`€${value.toFixed(2)}`, 'Paper equity']}
                labelFormatter={(v: string) => new Date(v).toLocaleString()}
              />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#4A90D9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      {champion.recent_orders.length > 0 && (
        <table className="mt-2 w-full border-collapse text-left font-mono text-[11px]">
          <thead>
            <tr className="border-b border-border/50 text-muted-foreground uppercase">
              <th className="py-1 pr-3 font-medium">Side</th>
              <th className="py-1 pr-3 font-medium">Qty</th>
              <th className="py-1 pr-3 font-medium">Fill price</th>
              <th className="py-1 pr-3 font-medium">Status</th>
              <th className="py-1 pr-3 font-medium">Submitted</th>
            </tr>
          </thead>
          <tbody>
            {champion.recent_orders.slice(0, 5).map((order) => (
              <tr key={order.id} className="border-b border-border/30">
                <td className="py-1 pr-3">{order.side}</td>
                <td className="py-1 pr-3">{order.qty}</td>
                <td className="py-1 pr-3">
                  {order.avg_fill_price !== null ? `€${order.avg_fill_price.toFixed(2)}` : '—'}
                </td>
                <td className="py-1 pr-3">{order.status}</td>
                <td className="py-1 pr-3 text-muted-foreground">
                  {new Date(order.submitted_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** SECTION -- PAPER TRADING (Harbour). One card per CHAMPION-status
 * strategy: its real mark-to-market equity curve (built from actual
 * fills via paper.reconciliation.compute_paper_equity_curve, not
 * simulated), recent orders, and any PAPER_WORSE_THAN_HOLDING /
 * PAPER_DIVERGENCE findings. No live benchmark overlay in v1 -- see
 * prometheus/api/routes/paper.py's module docstring for why (cost
 * discipline: no pre-computed per-champion benchmark table exists yet).
 * Honest empty state: zero strategies have ever reached CHAMPION status
 * (every validated strategy so far is REJECT). */
export function PaperTradingSection() {
  const { data, isLoading } = usePaperTradingQuery(DASHBOARD_POLL_MS);
  const champions = data?.champions ?? [];

  return (
    <Section
      storageKey="paper-trading"
      title={`Paper trading (${data?.total ?? 0})`}
      description="Harbour: real paper-traded champions, mark-to-market equity from actual fills."
      isEmpty={!isLoading && champions.length === 0}
      emptyLabel="Harbour — no champion yet (needs a VALIDATED strategy first; every strategy so far is REJECT)"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-3">
          {champions.map((champion) => (
            <ChampionCard key={champion.strategy_id} champion={champion} />
          ))}
        </div>
      )}
    </Section>
  );
}
