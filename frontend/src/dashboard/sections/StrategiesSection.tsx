'use client';

import { useStrategiesQuery } from '../../data/queries';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

/** SECTION 4 -- STRATEGIES. `strategies` rows are real the moment anyone
 * runs the deterministic grid (research/generate.py), which predates
 * Prompt 7's generation/evolution work -- so this reads the real
 * /strategies/ endpoint rather than a static "Prompt 7" placeholder.
 * OOS Sharpe / PBO / DSR significant / vs_benchmark / generation / parent
 * don't exist server-side yet (no validation layer, no lineage on
 * `strategies` itself) -- rendered as "—", not fabricated and not
 * hidden, so the table's shape already matches what Prompt 5/7 will
 * fill in. */
export function StrategiesSection() {
  const { data, isLoading } = useStrategiesQuery(DASHBOARD_POLL_MS);
  const strategies = data?.strategies ?? [];

  return (
    <Section
      storageKey="strategies"
      title={`Strategies (${data?.total ?? 0})`}
      isEmpty={!isLoading && strategies.length === 0}
      emptyLabel="Forge — no strategy has run yet (research/generate.py --generate, or Prompt 7's evolution loop)"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground uppercase">
                <th className="py-1.5 pr-4 font-medium">ID</th>
                <th className="py-1.5 pr-4 font-medium">Family</th>
                <th className="py-1.5 pr-4 font-medium">Status</th>
                <th className="py-1.5 pr-4 font-medium">OOS Sharpe</th>
                <th className="py-1.5 pr-4 font-medium">PBO</th>
                <th className="py-1.5 pr-4 font-medium">DSR sig.</th>
                <th className="py-1.5 pr-4 font-medium">vs benchmark</th>
                <th className="py-1.5 pr-4 font-medium">Generation</th>
                <th className="py-1.5 pr-4 font-medium">Parent</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s.id} className="border-b border-border/50">
                  <td className="py-1.5 pr-4">{s.id}</td>
                  <td className="py-1.5 pr-4">{s.family}</td>
                  <td className="py-1.5 pr-4">{s.status}</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                  <td className="py-1.5 pr-4 text-muted-foreground">—</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground">
            OOS Sharpe / PBO / DSR / vs_benchmark / generation / parent land in Prompt 5 (validation)
            and Prompt 7 (lineage).
          </p>
        </div>
      )}
    </Section>
  );
}
