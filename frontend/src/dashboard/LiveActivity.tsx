'use client';

import { useQueueQuery, useStrategiesQuery } from '../data/queries';
import type { InFlightJob, StrategyRow } from '../types';

const DASHBOARD_POLL_MS = 10000;
const RECENT_MUTATIONS_LIMIT = 5;

// Deliberately breaks from the rest of this dashboard's plain-text, no-
// icons convention (SystemsTable/LawsSection etc.) for this one panel --
// real progress bars and colored chips, not another table. The user asked
// specifically for "this is currently mutating", "this is currently being
// backtested" to read at a glance, not as more rows to parse.
const FAMILY_COLOR: Record<string, string> = {
  MOMENTUM: 'border-amber-500/60 text-amber-700 dark:text-amber-400',
  BOLLINGER: 'border-violet-500/60 text-violet-700 dark:text-violet-400',
  VOL_BREAKOUT: 'border-cyan-500/60 text-cyan-700 dark:text-cyan-400',
};

function familyClass(family: string | null): string {
  return family
    ? (FAMILY_COLOR[family] ?? 'border-border text-muted-foreground')
    : 'border-border text-muted-foreground';
}

function BacktestRow({ job }: { job: InFlightJob }) {
  const pct = Math.round(job.progress_pct * 100);
  return (
    <div className="flex items-center gap-3 py-1 font-mono text-xs">
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${familyClass(job.family)}`}>
        {job.family ?? '—'}
      </span>
      <span className="w-24 shrink-0 truncate text-muted-foreground">{job.symbol ?? '—'}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-emerald-500 transition-[width]"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-right tabular-nums">{pct}%</span>
      <span className="w-28 shrink-0 truncate text-muted-foreground">
        {job.current_stage} → {job.next_stage}
      </span>
    </div>
  );
}

function MutationRow({ strategy }: { strategy: StrategyRow }) {
  return (
    <div className="flex items-center gap-2 py-1 font-mono text-xs">
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${familyClass(strategy.family)}`}>
        {strategy.parent ?? '?'}
      </span>
      <span className="shrink-0 text-muted-foreground">
        ──{strategy.mutation_label ?? 'mutation'}──▶
      </span>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${familyClass(strategy.family)}`}>
        {strategy.id}
      </span>
    </div>
  );
}

/** Always-visible glance panel, not a collapsible Section -- "what's
 * happening right now" answered visually: real backtest progress bars
 * (GET /queue/'s in_flight jobs, kind=run_backtest) and recent parent→child
 * mutation chips (GET /strategies/'s generation/parent/mutation_label,
 * already server-resolved). Both empty states are honest, not hidden. */
export function LiveActivity() {
  const { data: queueData, isLoading: queueLoading } = useQueueQuery(DASHBOARD_POLL_MS);
  const { data: strategyData, isLoading: strategiesLoading } = useStrategiesQuery(DASHBOARD_POLL_MS);

  if (queueLoading || strategiesLoading) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-muted-foreground">
        Loading live activity…
      </div>
    );
  }

  const backtests = (queueData?.in_flight ?? []).filter((job) => job.kind === 'run_backtest');
  const mutations = (strategyData?.strategies ?? [])
    .filter((s) => s.generation > 0 && s.parent !== null)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, RECENT_MUTATIONS_LIMIT);

  if (backtests.length === 0 && mutations.length === 0) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-muted-foreground">
        Live activity — nothing running or mutating right now
      </div>
    );
  }

  return (
    <div className="space-y-3 border-b border-border bg-muted/20 px-4 py-3">
      {backtests.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            ● Backtesting now ({backtests.length})
          </p>
          {backtests.map((job) => (
            <BacktestRow key={job.id} job={job} />
          ))}
        </div>
      )}
      {mutations.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            ● Mutating now
          </p>
          {mutations.map((strategy) => (
            <MutationRow key={strategy.id} strategy={strategy} />
          ))}
        </div>
      )}
    </div>
  );
}
