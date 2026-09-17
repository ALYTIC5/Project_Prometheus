'use client';

import type { WorldState } from '../../types';
import { Section } from './Section';

interface LawsSectionProps {
  world: WorldState | null;
  isLoading: boolean;
}

/** SECTION 7 -- LAWS. WorldState.laws, verbatim -- all 8, live compliant/
 * last_violation. Note: projection.py's LAWS array is a static list today
 * (compliant is always hardcoded true, including law 7) -- it does not
 * yet reflect research_violations rows. The loud red banner Dashboard.tsx
 * renders at the top of the page is driven by GET /violations/ directly,
 * which IS real, rather than by this array. Not fixed here: doing so
 * means editing world/projection.py, which this prompt is keeping exact. */
export function LawsSection({ world, isLoading }: LawsSectionProps) {
  const laws = world?.laws ?? [];

  return (
    <Section
      storageKey="laws"
      title="Laws"
      description="Watchtower: live pass/fail status of every immutable law in tests/laws/."
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <table className="w-full border-collapse text-left font-mono text-xs">
          <thead>
            <tr className="border-b border-border text-muted-foreground uppercase">
              <th className="py-1.5 pr-4 font-medium">#</th>
              <th className="py-1.5 pr-4 font-medium">Law</th>
              <th className="py-1.5 pr-4 font-medium">Compliant</th>
              <th className="py-1.5 pr-4 font-medium">Last violation</th>
            </tr>
          </thead>
          <tbody>
            {laws.map((law) => (
              <tr key={law.law_id} className="border-b border-border/50">
                <td className="py-1.5 pr-4">{law.law_id}</td>
                <td className="py-1.5 pr-4" title={law.summary}>
                  {law.name}
                </td>
                <td className={`py-1.5 pr-4 ${law.compliant ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                  {law.compliant ? 'YES' : 'NO'}
                </td>
                <td className="py-1.5 pr-4 text-muted-foreground">{law.last_violation ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}
