'use client';

import { Fragment, useState } from 'react';
import { useExperimentDetailQuery, useExperimentsQuery } from '../../data/queries';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

interface ExpandedRowProps {
  experimentId: string;
}

function ExpandedRow({ experimentId }: ExpandedRowProps) {
  const { data, isLoading } = useExperimentDetailQuery(experimentId);
  if (isLoading) return <p className="py-2 text-muted-foreground">Loading…</p>;
  if (!data) return null;
  return (
    <div className="space-y-2 py-2">
      <div>
        <p className="text-muted-foreground uppercase">Results</p>
        <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">
          {JSON.stringify(data.results, null, 2)}
        </pre>
      </div>
      <div>
        <p className="text-muted-foreground uppercase">Decisions</p>
        <pre className="overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">
          {JSON.stringify(data.decisions, null, 2)}
        </pre>
      </div>
    </div>
  );
}

/** SECTION 5 -- EXPERIMENTS. Real data, GET /experiments/ (Prompt 4,
 * already built) -- hypothesis and decision/reason_codes come from the
 * migration 0006 columns and the nested latest decision respectively.
 * Click a row to expand its full results/decisions arrays via
 * GET /experiments/{id}, fetched on demand, not pre-loaded for every
 * row. */
export function ExperimentsSection() {
  const { data, isLoading } = useExperimentsQuery(DASHBOARD_POLL_MS);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const experiments = data?.experiments ?? [];

  return (
    <Section
      storageKey="experiments"
      title={`Experiments (${data?.total ?? 0})`}
      description="Arena: every backtest run, its lineage (parent experiment, hypothesis, change_set)."
      isEmpty={!isLoading && experiments.length === 0}
      emptyLabel="Arena — no experiment has run yet (experiments/runner.py)"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground uppercase">
                <th className="py-1.5 pr-4 font-medium">ID</th>
                <th className="py-1.5 pr-4 font-medium">Strategy</th>
                <th className="py-1.5 pr-4 font-medium">Hypothesis</th>
                <th className="py-1.5 pr-4 font-medium">Decision</th>
                <th className="py-1.5 pr-4 font-medium">Reason codes</th>
                <th className="py-1.5 pr-4 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => {
                const strategyId =
                  typeof e.payload.strategy_id === 'string' ? e.payload.strategy_id : '—';
                const expanded = expandedId === e.id;
                return (
                  <Fragment key={e.id}>
                    <tr
                      onClick={() => setExpandedId(expanded ? null : e.id)}
                      className="cursor-pointer border-b border-border/50 hover:bg-muted/40"
                    >
                      <td className="py-1.5 pr-4">{e.id}</td>
                      <td className="py-1.5 pr-4">{strategyId}</td>
                      <td className="max-w-xs truncate py-1.5 pr-4 text-muted-foreground" title={e.hypothesis ?? undefined}>
                        {e.hypothesis ?? '—'}
                      </td>
                      <td className="py-1.5 pr-4">{e.decision?.decision ?? e.status}</td>
                      <td className="py-1.5 pr-4 text-muted-foreground">
                        {e.decision?.reason_codes?.join(', ') ?? '—'}
                      </td>
                      <td className="py-1.5 pr-4 text-muted-foreground">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="border-b border-border/50">
                        <td colSpan={6}>
                          <ExpandedRow experimentId={e.id} />
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
