'use client';

import { useClustersQuery } from '../../data/queries';
import type { StrategyCluster } from '../../types';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

function ClusterCard({ cluster }: { cluster: StrategyCluster }) {
  return (
    <div className="rounded border border-border p-3">
      <div className="mb-2 flex items-center justify-between font-mono text-xs">
        <span className="font-semibold">
          {cluster.members.length} strategies, one discovery
        </span>
        <span className="text-muted-foreground">
          mean r = {cluster.mean_pairwise_correlation.toFixed(3)}
        </span>
      </div>
      <table className="w-full border-collapse text-left font-mono text-[11px]">
        <thead>
          <tr className="border-b border-border/50 text-muted-foreground uppercase">
            <th className="py-1 pr-3 font-medium">Strategy</th>
            <th className="py-1 pr-3 font-medium">Family</th>
            <th className="py-1 pr-3 font-medium">Role</th>
            <th className="py-1 pr-3 font-medium">Score</th>
            <th className="py-1 pr-3 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {cluster.members
            .slice()
            .sort((a, b) => (b.is_representative ? 1 : 0) - (a.is_representative ? 1 : 0))
            .map((member) => (
              <tr key={member.config_hash} className="border-b border-border/30">
                <td className="py-1 pr-3">{member.strategy_id ?? member.config_hash.slice(0, 8)}</td>
                <td className="py-1 pr-3">{member.family ?? '—'}</td>
                <td className="py-1 pr-3">
                  {member.is_representative ? (
                    <span className="text-emerald-600 dark:text-emerald-400">representative</span>
                  ) : (
                    <span className="text-muted-foreground">redundant variant</span>
                  )}
                </td>
                <td className="py-1 pr-3">{member.score !== null ? member.score.toFixed(1) : '—'}</td>
                <td className="py-1 pr-3 text-muted-foreground">{member.verdict ?? '—'}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

/** SECTION -- STRATEGY CLUSTERS. The "100 strategies" prompt's own
 * explicit ask: real return-stream correlation clustering, so several
 * near-duplicate parameterizations of the same underlying signal (e.g.
 * SMA/EMA/DEMA crossovers) don't get counted as independent
 * discoveries. Computed fresh every validation cycle
 * (experiments/runner.py's validate_specs), read-only here -- does NOT
 * yet change which cluster member is CHAMPION-eligible (see
 * docs/DEFERRED.md for why that's separate, more carefully reviewed
 * follow-up work). Only real clusters (>1 member) are shown; a
 * singleton isn't redundancy, it's just an ordinary strategy. */
export function ClustersSection() {
  const { data, isLoading } = useClustersQuery(DASHBOARD_POLL_MS);
  const clusters = data?.clusters ?? [];

  return (
    <Section
      storageKey="clusters"
      title={`Strategy clusters (${data?.total ?? 0})`}
      description="Correlation clustering: strategies whose return streams move together count as one discovery, not several."
      isEmpty={!isLoading && clusters.length === 0}
      emptyLabel="No correlated clusters found yet — every validated strategy so far looks like a distinct signal"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-3">
          {clusters.map((cluster) => (
            <ClusterCard key={cluster.cluster_key} cluster={cluster} />
          ))}
        </div>
      )}
    </Section>
  );
}
