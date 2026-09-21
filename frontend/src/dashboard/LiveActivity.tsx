'use client';

import { useState } from 'react';
import { useQueueQuery, useResearchPapersQuery, useStrategiesQuery } from '../data/queries';
import type { InFlightJob, ResearchPaperRow, StrategyRow } from '../types';
import { assetClassBadgeClass, assetClassLabel } from './assetClass';
import { DetailModal, type DetailTarget } from './DetailModal';

const DASHBOARD_POLL_MS = 10000;
const RECENT_MUTATIONS_LIMIT = 5;
const RECENT_HYPOTHESES_LIMIT = 5;
const RECENT_PAPERS_LIMIT = 5;

// Deliberately breaks from the rest of this dashboard's plain-text, no-
// icons convention (SystemsTable/LawsSection etc.) for this one panel --
// real progress bars and colored chips, not another table. The user asked
// specifically for "this is currently mutating", "this is currently being
// backtested" to read at a glance, not as more rows to parse.
const FAMILY_COLOR: Record<string, string> = {
  MOMENTUM: 'border-amber-500/60 text-amber-700 dark:text-amber-400',
  BOLLINGER: 'border-violet-500/60 text-violet-700 dark:text-violet-400',
  VOL_BREAKOUT: 'border-cyan-500/60 text-cyan-700 dark:text-cyan-400',
  RSI: 'border-rose-500/60 text-rose-700 dark:text-rose-400',
  MACD: 'border-lime-500/60 text-lime-700 dark:text-lime-400',
  RANDOM_FOREST: 'border-sky-500/60 text-sky-700 dark:text-sky-400',
  GRADIENT_BOOSTING: 'border-indigo-500/60 text-indigo-700 dark:text-indigo-400',
  LOGISTIC_REGRESSION: 'border-emerald-500/60 text-emerald-700 dark:text-emerald-400',
  SVM: 'border-red-500/60 text-red-700 dark:text-red-400',
  STOCHASTIC: 'border-fuchsia-500/60 text-fuchsia-700 dark:text-fuchsia-400',
  PARABOLIC_SAR: 'border-orange-500/60 text-orange-700 dark:text-orange-400',
  KELTNER: 'border-teal-500/60 text-teal-700 dark:text-teal-400',
  WILLIAMS_R: 'border-pink-500/60 text-pink-700 dark:text-pink-400',
  CCI: 'border-yellow-500/60 text-yellow-700 dark:text-yellow-400',
  AWESOME_OSCILLATOR: 'border-purple-500/60 text-purple-700 dark:text-purple-400',
  SUPERTREND: 'border-green-500/60 text-green-700 dark:text-green-400',
  TRIX: 'border-blue-500/60 text-blue-700 dark:text-blue-400',
};

function familyClass(family: string | null): string {
  return family
    ? (FAMILY_COLOR[family] ?? 'border-border text-muted-foreground')
    : 'border-border text-muted-foreground';
}

function BacktestRow({ job, onClick }: { job: InFlightJob; onClick: () => void }) {
  const pct = Math.round(job.progress_pct * 100);
  return (
    <div
      onClick={onClick}
      className="flex cursor-pointer items-center gap-3 rounded py-1 font-mono text-xs hover:bg-muted/40"
    >
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

function MutationRow({ strategy, onClick }: { strategy: StrategyRow; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex cursor-pointer items-center gap-2 rounded py-1 font-mono text-xs hover:bg-muted/40"
    >
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${assetClassBadgeClass(strategy.asset_class)}`}>
        {assetClassLabel(strategy.asset_class)}
      </span>
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

function HypothesisRow({ strategy, onClick }: { strategy: StrategyRow; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex cursor-pointer items-center gap-2 rounded py-1 font-mono text-xs hover:bg-muted/40"
    >
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${assetClassBadgeClass(strategy.asset_class)}`}>
        {assetClassLabel(strategy.asset_class)}
      </span>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 ${familyClass(strategy.family)}`}>
        {strategy.id}
      </span>
      <span className="truncate text-muted-foreground">
        {strategy.verdict ?? 'awaiting backtest'}
      </span>
    </div>
  );
}

function PaperRow({ paper, onClick }: { paper: ResearchPaperRow; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="flex cursor-pointer items-center gap-2 rounded py-1 font-mono text-xs hover:bg-muted/40"
    >
      <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-muted-foreground">
        {paper.arxiv_id}
      </span>
      <span className="truncate">{paper.title}</span>
    </div>
  );
}

function isLlmHypothesis(strategy: StrategyRow): boolean {
  const source = (strategy.spec as { source?: unknown }).source;
  return source === 'llm_hypothesis';
}

/** Always-visible glance panel, not a collapsible Section -- "what's
 * happening right now" answered visually: real backtest progress bars
 * (GET /queue/'s in_flight jobs, kind=run_backtest), recent parent→child
 * mutation chips, recent LLM hypotheses (GET /strategies/'s
 * generation/parent/mutation_label/spec.source, already server-resolved),
 * and recently ingested papers (GET /research-papers/). Every row opens
 * DetailModal on click. All empty states are honest, not hidden. */
export function LiveActivity() {
  const { data: queueData, isLoading: queueLoading } = useQueueQuery(DASHBOARD_POLL_MS);
  const { data: strategyData, isLoading: strategiesLoading } = useStrategiesQuery(DASHBOARD_POLL_MS);
  const { data: paperData, isLoading: papersLoading } = useResearchPapersQuery(DASHBOARD_POLL_MS);
  const [target, setTarget] = useState<DetailTarget | null>(null);

  if (queueLoading || strategiesLoading || papersLoading) {
    return (
      <div className="border-b border-border px-4 py-3 font-mono text-xs text-muted-foreground">
        Loading live activity…
      </div>
    );
  }

  const backtests = (queueData?.in_flight ?? []).filter((job) => job.kind === 'run_backtest');
  const hypotheses = (strategyData?.strategies ?? [])
    .filter(isLlmHypothesis)
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, RECENT_HYPOTHESES_LIMIT);
  const mutations = (strategyData?.strategies ?? [])
    .filter((s) => s.generation > 0 && s.parent !== null && !isLlmHypothesis(s))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, RECENT_MUTATIONS_LIMIT);
  const papers = (paperData?.papers ?? []).slice(0, RECENT_PAPERS_LIMIT);

  if (backtests.length === 0 && mutations.length === 0 && hypotheses.length === 0 && papers.length === 0) {
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
            <BacktestRow key={job.id} job={job} onClick={() => setTarget({ kind: 'job', job })} />
          ))}
        </div>
      )}
      {mutations.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            ● Mutating now
          </p>
          {mutations.map((strategy) => (
            <MutationRow
              key={strategy.id}
              strategy={strategy}
              onClick={() => setTarget({ kind: 'strategy', id: strategy.id })}
            />
          ))}
        </div>
      )}
      {hypotheses.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            ● LLM hypotheses proposed
          </p>
          {hypotheses.map((strategy) => (
            <HypothesisRow
              key={strategy.id}
              strategy={strategy}
              onClick={() => setTarget({ kind: 'strategy', id: strategy.id })}
            />
          ))}
        </div>
      )}
      {papers.length > 0 && (
        <div>
          <p className="mb-1 font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
            ● Papers ingested
          </p>
          {papers.map((paper) => (
            <PaperRow key={paper.id} paper={paper} onClick={() => setTarget({ kind: 'paper', paper })} />
          ))}
        </div>
      )}
      <DetailModal target={target} onClose={() => setTarget(null)} />
    </div>
  );
}
