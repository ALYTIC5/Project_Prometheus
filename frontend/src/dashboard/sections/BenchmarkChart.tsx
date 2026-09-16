'use client';

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useBenchmarkCurveQuery } from '../../data/queries';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

/** SECTION 2 -- BENCHMARK. The €1,000 buy-and-hold equity curve. Law 8:
 * this line is permanent and has no toggle to hide it, same posture as
 * BenchmarkStrip in the header. Once system equity exists (Prompt 8+) a
 * second line overlays here; today benchmark-only is the correct state,
 * not a placeholder -- there is no system portfolio yet. */
export function BenchmarkChart() {
  const { data: curve, isLoading } = useBenchmarkCurveQuery(DASHBOARD_POLL_MS);
  const points = curve ?? [];

  return (
    <Section
      storageKey="benchmark"
      title="Benchmark"
      isEmpty={!isLoading && points.length === 0}
      emptyLabel="Library — real historical curve lands in Prompt 2 (currently today's point only)"
    >
      <div className="h-64 w-full font-mono text-xs">
        {isLoading ? (
          <p className="py-2 text-sm text-muted-foreground">Loading…</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
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
                formatter={(value: number) => [`€${value.toFixed(2)}`, 'Buy & hold']}
                labelFormatter={(v: string) => new Date(v).toLocaleString()}
              />
              <Line
                // --chart-1 is a near-white greyscale token today (see
                // app/globals.css) -- invisible against a light background.
                // This project's existing accent blue (WorldView.tsx's
                // heading color) instead, until the chart palette is
                // deliberately designed rather than defaulted.
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
    </Section>
  );
}
