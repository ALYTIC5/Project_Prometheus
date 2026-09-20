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
import { useExperimentsQuery } from '../../data/queries';
import type { ExperimentRow } from '../../types';
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

interface ScatterPoint {
  id: string;
  decision: string | null;
  benchmark_return_pct: number;
  total_return_pct: number;
}

function toPoints(experiments: ExperimentRow[]): ScatterPoint[] {
  return experiments
    .filter((e) => e.total_return_pct !== null && e.benchmark_return_pct !== null)
    .map((e) => ({
      id: e.id,
      decision: e.decision?.decision ?? null,
      benchmark_return_pct: e.benchmark_return_pct as number,
      total_return_pct: e.total_return_pct as number,
    }));
}

function domainFor(points: ScatterPoint[]): [number, number] {
  const values = points.flatMap((p) => [p.benchmark_return_pct, p.total_return_pct]);
  if (values.length === 0) return [-1, 1];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max((max - min) * 0.1, 0.5);
  return [min - pad, max + pad];
}

/** SECTION -- BACKTEST RESULTS. Every backtest ever run (last 200), one
 * dot each: x = the same €1,000 buy-and-hold return every Law 8
 * comparison uses, y = the strategy's own return, both net of costs
 * (results.payload, GET /experiments/'s own latest-result LATERAL join --
 * no separate endpoint, no recomputation). Above the diagonal beat
 * benchmark; below it didn't. Colored by the experiment's latest
 * decision. This is the honest aggregate view Law 8 asks for: with 1176
 * experiments and 0 ever beating benchmark net of costs, the chart is
 * expected to show almost everything below the line -- that is the
 * finding, not a bug in the chart. */
export function BacktestScatterSection() {
  const { data, isLoading } = useExperimentsQuery(DASHBOARD_POLL_MS);
  const points = toPoints(data?.experiments ?? []);
  const [domainMin, domainMax] = domainFor(points);

  return (
    <Section
      storageKey="backtest-scatter"
      title={`Backtest results (${points.length})`}
      description="Oracle: strategy return vs. the same Buy & Hold benchmark (Law 8), one dot per backtest."
      isEmpty={!isLoading && points.length === 0}
      emptyLabel="Oracle — no completed backtest with a recorded result yet"
    >
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
                    <p className="font-semibold">{p.id}</p>
                    <p>Strategy: {p.total_return_pct.toFixed(2)}%</p>
                    <p>Benchmark: {p.benchmark_return_pct.toFixed(2)}%</p>
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
