'use client';

import { useQueueQuery, useStrategiesQuery } from '../data/queries';

const DASHBOARD_POLL_MS = 10000;

// strategies.status's real lifecycle vocabulary -- research/population.py's
// STRATEGY_STATES, plus "pending" (Strategy.status's own default for a row
// freshly written by research/generate.py, before any validation cycle has
// touched it). Ordered by how far along the pipeline a strategy has gotten,
// so the glance row reads left-to-right as progress, not alphabetically.
const STATUS_ORDER = [
  'CHAMPION',
  'VALIDATED',
  'PROMISING',
  'REGIME_SPECIALIST',
  'EXPERIMENTAL',
  'pending',
  'DORMANT',
  'QUARANTINED',
  'REJECTED',
  'RETIRED',
] as const;

const STATUS_STYLE: Record<string, string> = {
  CHAMPION: 'text-emerald-600 dark:text-emerald-400',
  VALIDATED: 'text-emerald-600 dark:text-emerald-400',
  PROMISING: 'text-emerald-600 dark:text-emerald-400',
  REGIME_SPECIALIST: 'text-amber-600 dark:text-amber-400',
  EXPERIMENTAL: 'text-amber-600 dark:text-amber-400',
  pending: 'text-muted-foreground',
  DORMANT: 'text-muted-foreground',
  QUARANTINED: 'text-red-600 dark:text-red-400',
  REJECTED: 'text-red-600 dark:text-red-400',
  RETIRED: 'text-red-600 dark:text-red-400',
};

/** Always-visible glance strip -- NOT a collapsible Section, because this
 * is exactly the "what's going on right now" summary a viewer shouldn't
 * have to open anything to see. Answers three questions at a glance:
 * (1) population breakdown by real lifecycle status, (2) how deep the
 * evolution has gone (max generation) and whether anything has reached
 * CHAMPION, (3) whether backtesting is actively running right now.
 * Everything here is derived from data StrategiesSection/QueueSection
 * already fetch (useStrategiesQuery/useQueueQuery) -- no new endpoint. */
export function ResearchSummary() {
  const strategiesQuery = useStrategiesQuery(DASHBOARD_POLL_MS);
  const queueQuery = useQueueQuery(DASHBOARD_POLL_MS);
  const { data: strategyData, isLoading: strategiesLoading } = strategiesQuery;
  const { data: queueData, isLoading: queueLoading } = queueQuery;
  const strategies = strategyData?.strategies ?? [];

  const failed = [strategiesQuery, queueQuery].find((q) => q.isError);
  if (failed) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-red-400">
        Research summary unavailable: {String(failed.error)}
      </div>
    );
  }

  if (strategiesLoading || queueLoading) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-muted-foreground">
        Loading research summary…
      </div>
    );
  }

  const counts = new Map<string, number>();
  for (const s of strategies) {
    counts.set(s.status, (counts.get(s.status) ?? 0) + 1);
  }
  const maxGeneration = strategies.reduce((max, s) => Math.max(max, s.generation), 0);
  const champions = strategies.filter((s) => s.status === 'CHAMPION');
  const bestScore = strategies.reduce<number | null>(
    (best, s) => (s.score !== null && (best === null || s.score > best) ? s.score : best),
    null,
  );
  const pendingDepth = Object.values(queueData?.pending_by_kind ?? {}).reduce((a, b) => a + b, 0);
  const inFlight = queueData?.in_flight.length ?? 0;

  if (strategies.length === 0) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-muted-foreground">
        Research summary — no strategy has run yet (research/generate.py, or Prompt 7's evolution loop)
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-border bg-muted/20 px-4 py-3 font-mono text-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {STATUS_ORDER.filter((status) => (counts.get(status) ?? 0) > 0).map((status) => (
          <span key={status} className={STATUS_STYLE[status] ?? 'text-muted-foreground'}>
            {status}: <strong>{counts.get(status)}</strong>
          </span>
        ))}
      </div>
      <span aria-hidden="true" className="text-border">
        |
      </span>
      <span>
        Generation: <strong>{maxGeneration}</strong>
      </span>
      <span>
        Champions: <strong className={champions.length > 0 ? 'text-emerald-600 dark:text-emerald-400' : ''}>{champions.length}</strong>
      </span>
      <span>
        Best score: <strong>{bestScore !== null ? bestScore.toFixed(1) : '—'}</strong>
      </span>
      <span aria-hidden="true" className="text-border">
        |
      </span>
      <span>
        Backtests running: <strong className={inFlight > 0 ? 'text-emerald-600 dark:text-emerald-400' : ''}>{inFlight}</strong>
      </span>
      <span>
        Queued: <strong>{pendingDepth}</strong>
      </span>
    </div>
  );
}
