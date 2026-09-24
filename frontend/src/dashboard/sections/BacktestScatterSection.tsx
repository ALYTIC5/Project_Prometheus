'use client';

import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useExperimentsScatterQuery } from '../../data/queries';
import type { ScatterPointRow } from '../../types';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

// Colors only, for recharts fill -- not Tailwind classes. Mirrors
// StrategiesSection.tsx's VERDICT_STYLE groupings; ACCEPT is the quick
// pre-validation check runner.py writes on every backtest (not yet a
// full Oracle verdict), grouped with the PROMOTE/PROMISING greens since
// both mean "beat benchmark net of costs".
const DECISION_COLOR: Record<string, string> = {
  ACCEPT: '#059669',
  PROMOTE: '#059669',
  PROMISING: '#059669',
  CONTINUE_RESEARCH: '#d97706',
  REGIME_SPECIALIST: '#d97706',
  DORMANT: '#6b7280',
  QUARANTINE: '#dc2626',
  REJECT: '#dc2626',
  RETIRE: '#dc2626',
};

function decisionColor(decision: string | null): string {
  return decision ? (DECISION_COLOR[decision] ?? '#6b7280') : '#6b7280';
}

type ScatterPoint = ScatterPointRow & { label: string };

function universeLabel(p: ScatterPointRow): string {
  if (p.symbol) return p.symbol;
  if (p.universe?.length) return `${p.universe.length}-asset: ${p.universe.join(', ')}`;
  return 'unknown universe';
}

function toPoints(rows: ScatterPointRow[]): ScatterPoint[] {
  return rows.map((r) => ({ ...r, label: universeLabel(r) }));
}

/** Law 8 sanity check on what's plotted. Identical benchmark returns are
 * CORRECT within one universe over one window, and a bug across different
 * universes -- so this compares exact values per universe rather than
 * applying an invented "near zero" variance cutoff. */
function benchmarkHealth(points: ScatterPoint[]): { universes: number; suspicious: boolean } {
  const byUniverse = new Map<string, Set<number>>();
  for (const p of points) {
    const set = byUniverse.get(p.label) ?? new Set<number>();
    set.add(p.benchmark_return_pct);
    byUniverse.set(p.label, set);
  }
  const distinct = new Set(points.map((p) => p.benchmark_return_pct));
  return { universes: byUniverse.size, suspicious: byUniverse.size > 1 && distinct.size === 1 };
}

function domainFor(points: ScatterPoint[]): [number, number] {
  const values = points.flatMap((p) => [p.benchmark_return_pct, p.total_return_pct]);
  if (values.length === 0) return [-1, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max((max - min) * 0.1, 0.5);
  return [min - pad, max + pad];
}

/** SECTION -- BACKTEST RESULTS. One dot per spec (its latest result),
 * across every symbol and universe (GET /experiments/scatter): x = the
 * €1,000 buy-and-hold of that spec's OWN universe over its OWN window
 * (Law 8), y = the strategy's own return, both net of costs. Above the
 * diagonal beat its benchmark; below it didn't. Colored by latest
 * decision; hover shows the symbol/universe and benchmark window. */
export function BacktestScatterSection() {
  const { data, isLoading } = useExperimentsScatterQuery(DASHBOARD_POLL_MS);
  const points = toPoints(data?.points ?? []);
  const [domainMin, domainMax] = domainFor(points);
  const health = benchmarkHealth(points);
  const legacy = points.filter((p) => p.benchmark_universe === null).length;

  return (
    <Section
      storageKey="backtest-scatter"
      title={`Backtest results (${points.length})`}
      description="Oracle: strategy return vs. the same Buy & Hold benchmark (Law 8), one dot per backtest."
      isEmpty={!isLoading && points.length === 0}
      emptyLabel="Oracle — no completed backtest with a recorded result yet"
    >
      {health.suspicious && (
        <div className="mb-2 rounded border border-red-900 bg-red-950/80 px-3 py-2 font-mono text-[11px] text-red-200">
          ⚠ {health.universes} different universes all report the SAME benchmark return — Law 8
          says each must be its own buy-and-hold. This is a bug, not a finding.
        </div>
      )}
      {legacy > 0 && (
        <p className="mb-2 font-mono text-[11px] text-muted-foreground">
          {legacy} of {points.length} results predate the 2026-09-24 benchmark fix (no recorded
          benchmark window) — superseded as specs are re-run.
        </p>
      )}
      <div className="h-72 w-full font-mono text-xs">
        {isLoading ? (
          <p className="py-2 text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              type="number"
              dataKey="benchmark_return_pct"
              name="Benchmark return"
              domain={[domainMin, domainMax]}
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              label={{ value: 'Benchmark return', position: 'insideBottom', offset: -4, fontSize: 10, fill: 'var(--muted-foreground)' }}
            />
            <YAxis
              type="number"
              dataKey="total_return_pct"
              name="Strategy return"
              domain={[domainMin, domainMax]}
              tick={{ fontSize: 10, fill: 'var(--muted-foreground)' }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              label={{ value: 'Strategy return', angle: -90, position: 'insideLeft', fontSize: 10, fill: 'var(--muted-foreground)' }}
            />
            <ReferenceLine
              segment={[
                { x: domainMin, y: domainMin },
                { x: domainMax, y: domainMax },
              ]}
              stroke="var(--muted-foreground)"
              strokeDasharray="4 4"
            />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as ScatterPoint;
                return (
                  <div className="rounded border border-border bg-background p-2 text-[11px] shadow">
                    <p className="font-semibold">{p.label}</p>
                    <p className="text-muted-foreground">
                      {p.family} · {p.id}
                    </p>
                    <p>Strategy: {p.total_return_pct.toFixed(2)}%</p>
                    <p>
                      Benchmark: {p.benchmark_return_pct.toFixed(2)}%
                      {p.benchmark_window?.[0]
                        ? ` (${p.benchmark_window[0]} → ${p.benchmark_window[1]})`
                        : ' (window not recorded)'}
                    </p>
                    <p className="text-muted-foreground">{p.decision ?? 'no decision yet'}</p>
                  </div>
                );
              }}
            />
            <Scatter
              data={points}
              isAnimationActive={false}
              fill="#4A90D9"
              shape={(props: unknown) => {
                const { cx, cy, payload } = props as { cx: number; cy: number; payload: ScatterPoint };
                return <circle cx={cx} cy={cy} r={3} fill={decisionColor(payload.decision)} fillOpacity={0.75} />;
              }}
            />
          </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>
    </Section>
  );
}
