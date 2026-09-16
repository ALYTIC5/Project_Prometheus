'use client';

import { useBuildingsQuery } from '../../data/queries';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

function phaseLabel(phase: string): string {
  return phase.toUpperCase();
}

/** SECTION 1 -- SYSTEMS. One row per construction-manifest building (12
 * total), replacing the whole construction-site metaphor with one table.
 * row_count/phase are both real (GET /buildings/, PROMPT S's row_count
 * addition) -- green text when ACTIVE, grey otherwise, no icons or
 * gauges (S.3: "every number is a number"). */
export function SystemsTable() {
  const { data, isLoading } = useBuildingsQuery(DASHBOARD_POLL_MS);
  const buildings = data?.buildings ?? [];

  return (
    <Section storageKey="systems" title={`Systems (${data?.total ?? 0}/12)`}>
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground uppercase">
                <th className="py-1.5 pr-4 font-medium">System</th>
                <th className="py-1.5 pr-4 font-medium">Status</th>
                <th className="py-1.5 pr-4 font-medium">Activates on</th>
                <th className="py-1.5 pr-4 font-medium">Rows</th>
                <th className="py-1.5 pr-4 font-medium">Prompt</th>
              </tr>
            </thead>
            <tbody>
              {buildings.map((b) => {
                const active = b.phase === 'active';
                return (
                  <tr key={b.id} className="border-b border-border/50">
                    <td className="py-1.5 pr-4">{b.id}</td>
                    <td className={`py-1.5 pr-4 ${active ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'}`}>
                      {phaseLabel(b.phase)}
                    </td>
                    <td className="py-1.5 pr-4 text-muted-foreground">
                      {b.activates_on.length ? b.activates_on.join(', ') : '—'}
                    </td>
                    <td className="py-1.5 pr-4">{b.row_count}</td>
                    <td className="py-1.5 pr-4 text-muted-foreground">{b.prompt ?? '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
