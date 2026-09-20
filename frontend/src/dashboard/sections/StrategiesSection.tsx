'use client';

import { Fragment, useState } from 'react';
import { useStrategiesQuery } from '../../data/queries';
import type { StrategyRow } from '../../types';
import { assetClassBadgeClass, assetClassLabel } from '../assetClass';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

// The overfit cutoff validation/decision.py actually uses (PBO's own
// cited convention, Bailey/Borwein/Lopez de Prado/Zhu 2015) -- reused
// here for color only, never re-decided client-side.
const PBO_OVERFIT_CUTOFF = 0.5;

const VERDICT_STYLE: Record<string, string> = {
  PROMOTE: 'text-emerald-600 dark:text-emerald-400',
  PROMISING: 'text-emerald-600 dark:text-emerald-400',
  CONTINUE_RESEARCH: 'text-amber-600 dark:text-amber-400',
  REGIME_SPECIALIST: 'text-amber-600 dark:text-amber-400',
  DORMANT: 'text-muted-foreground',
  QUARANTINE: 'text-red-600 dark:text-red-400',
  REJECT: 'text-red-600 dark:text-red-400',
  RETIRE: 'text-red-600 dark:text-red-400',
};

function verdictClass(verdict: string | null): string {
  return verdict ? (VERDICT_STYLE[verdict] ?? 'text-muted-foreground') : 'text-muted-foreground';
}

function formatPct(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function ExpandedRow({ strategy }: { strategy: StrategyRow }) {
  return (
    <div className="space-y-2 py-2">
      <div>
        <p className="text-muted-foreground uppercase">Spec parameters</p>
        <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">
          {JSON.stringify(strategy.spec, null, 2)}
        </pre>
      </div>
      {strategy.reason_codes.length > 0 && (
        <div>
          <p className="text-muted-foreground uppercase">Reason codes</p>
          <p className="font-mono text-[11px]">{strategy.reason_codes.join(', ')}</p>
        </div>
      )}
    </div>
  );
}

/** SECTION 4 -- STRATEGIES. Real validation and lineage data from
 * GET /strategies/ (Prompt 5's validator + Prompt 7's mutation lineage,
 * both already built -- see prometheus/api/routes/strategies.py's
 * _resolve_lineage/_enrich for where these columns actually come from).
 * Click a row to see its full spec and reason codes -- same expand
 * pattern ExperimentsSection already uses. */
export function StrategiesSection() {
  const { data, isLoading } = useStrategiesQuery(DASHBOARD_POLL_MS);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const strategies = data?.strategies ?? [];

  return (
    <Section
      storageKey="strategies"
      title={`Strategies (${data?.total ?? 0})`}
      description="Forge: every strategy ever generated, its verdict, and where it sits in the evolution lineage."
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
                <th className="py-1.5 pr-4 font-medium">Asset</th>
                <th className="py-1.5 pr-4 font-medium">Family</th>
                <th className="py-1.5 pr-4 font-medium">Verdict</th>
                <th className="py-1.5 pr-4 font-medium">Score</th>
                <th className="py-1.5 pr-4 font-medium">PBO</th>
                <th className="py-1.5 pr-4 font-medium">DSR</th>
                <th className="py-1.5 pr-4 font-medium">vs benchmark</th>
                <th className="py-1.5 pr-4 font-medium">Gen</th>
                <th className="py-1.5 pr-4 font-medium">Parent</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => {
                const expanded = expandedId === s.id;
                const overfit = s.pbo !== null && s.pbo > PBO_OVERFIT_CUTOFF;
                const dsrSurvives = s.deflated_sharpe !== null && s.deflated_sharpe > 0;
                return (
                  <Fragment key={s.id}>
                    <tr
                      onClick={() => setExpandedId(expanded ? null : s.id)}
                      className="cursor-pointer border-b border-border/50 hover:bg-muted/40"
                    >
                      <td className="py-1.5 pr-4">{s.id}</td>
                      <td className="py-1.5 pr-4">
                        <span
                          className={`rounded border px-1.5 py-0.5 ${assetClassBadgeClass(s.asset_class)}`}
                        >
                          {assetClassLabel(s.asset_class)}
                        </span>
                      </td>
                      <td className="py-1.5 pr-4">{s.family}</td>
                      <td className={`py-1.5 pr-4 ${verdictClass(s.verdict)}`}>
                        {s.verdict ?? 'UNVALIDATED'}
                      </td>
                      <td className="py-1.5 pr-4">{s.score !== null ? s.score.toFixed(1) : '—'}</td>
                      <td
                        className={`py-1.5 pr-4 ${overfit ? 'text-red-600 dark:text-red-400' : ''}`}
                        title={overfit ? `Above the ${PBO_OVERFIT_CUTOFF} overfit cutoff` : undefined}
                      >
                        {s.pbo !== null ? s.pbo.toFixed(2) : '—'}
                      </td>
                      <td
                        className={`py-1.5 pr-4 ${
                          s.deflated_sharpe !== null
                            ? dsrSurvives
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-red-600 dark:text-red-400'
                            : ''
                        }`}
                        title={
                          s.deflated_sharpe !== null
                            ? dsrSurvives
                              ? 'Survives deflation (DSR > 0)'
                              : 'Does not survive deflation (DSR ≤ 0)'
                            : undefined
                        }
                      >
                        {s.deflated_sharpe !== null ? s.deflated_sharpe.toFixed(2) : '—'}
                      </td>
                      <td
                        className={`py-1.5 pr-4 ${
                          s.excess_return !== null
                            ? s.excess_return > 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-red-600 dark:text-red-400'
                            : ''
                        }`}
                      >
                        {formatPct(s.excess_return)}
                      </td>
                      <td className="py-1.5 pr-4 text-muted-foreground">{s.generation}</td>
                      <td className="py-1.5 pr-4 text-muted-foreground">{s.parent ?? '—'}</td>
                    </tr>
                    {expanded && (
                      <tr className="border-b border-border/50">
                        <td colSpan={10}>
                          <ExpandedRow strategy={s} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}
