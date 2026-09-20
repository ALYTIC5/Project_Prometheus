'use client';

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../components/ui/dialog';
import { useStrategyDetailQuery } from '../data/queries';
import type { InFlightJob, PipelineConcern, ResearchPaperRow } from '../types';

export type DetailTarget =
  | { kind: 'strategy'; id: string }
  | { kind: 'job'; job: InFlightJob }
  | { kind: 'paper'; paper: ResearchPaperRow }
  | { kind: 'concern'; concern: PipelineConcern };

const CONCERN_DESCRIPTIONS: Record<string, string> = {
  ingest: 'Backfills real OHLCV bars for every symbol in the universe. Idempotent -- re-ingesting a known bar is a no-op.',
  research: 'Enqueues the deterministic grid, drains the backtest queue, re-validates every scored strategy against real PBO/DSR/decay/regime evidence, then runs one bounded evolution step (mutation + crossover) and one budget-gated LLM hypothesis.',
  paper: 'Ticks paper trading for every live champion: decides and submits orders, polls fills, reconciles against the real benchmark.',
  llm_ingestion: 'Searches arXiv for new quantitative-finance papers and extracts their key sections (via GROBID, falling back to raw PDF text) into research_papers.',
};

interface DetailModalProps {
  target: DetailTarget | null;
  onClose: () => void;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-border/50 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function StrategyDetail({ id }: { id: string }) {
  const { data, isLoading } = useStrategyDetailQuery(id);
  if (isLoading) return <p className="py-2 text-muted-foreground">Loading…</p>;
  if (!data) return <p className="py-2 text-muted-foreground">Not found.</p>;
  return (
    <div className="space-y-3 font-mono text-xs">
      <div>
        <Row label="Asset class" value={data.asset_class ?? 'unknown'} />
        <Row label="Family" value={data.family} />
        <Row label="Status" value={data.status} />
        <Row label="Verdict" value={data.verdict ?? '—'} />
        <Row label="Score" value={data.score !== null ? data.score.toFixed(4) : '—'} />
        <Row label="PBO" value={data.pbo !== null ? data.pbo.toFixed(4) : '—'} />
        <Row
          label="Deflated Sharpe"
          value={data.deflated_sharpe !== null ? data.deflated_sharpe.toFixed(4) : '—'}
        />
        <Row
          label="vs Benchmark (excess return)"
          value={data.excess_return !== null ? `${data.excess_return.toFixed(2)}%` : '—'}
        />
        <Row label="Generation" value={String(data.generation)} />
        <Row label="Parent" value={data.parent ?? '— (root)'} />
        <Row label="Mutation" value={data.mutation_label ?? '—'} />
        {data.reason_codes.length > 0 && (
          <Row label="Reason codes" value={data.reason_codes.join(', ')} />
        )}
      </div>
      <div>
        <p className="mb-1 text-muted-foreground uppercase">Spec</p>
        <pre className="overflow-x-auto rounded bg-muted/50 p-2">
          {JSON.stringify(data.spec, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function JobDetail({ job }: { job: InFlightJob }) {
  return (
    <div className="space-y-2 font-mono text-xs">
      <div>
        <Row label="Job ID" value={job.id} />
        <Row label="Kind" value={job.kind} />
        <Row label="Family" value={job.family ?? '—'} />
        <Row label="Symbol" value={job.symbol ?? '—'} />
        <Row label="Stage" value={`${job.current_stage} → ${job.next_stage}`} />
        <Row label="Progress" value={`${Math.round(job.progress_pct * 100)}%`} />
        <Row label="Agent role" value={job.agent_role} />
        {job.experiment_id !== null && <Row label="Experiment" value={job.experiment_id} />}
      </div>
      <p className="pt-2 text-muted-foreground">
        Still running — the backtest engine is replaying this strategy against real
        point-in-time data. Check back once it completes for the full verdict.
      </p>
    </div>
  );
}

function PaperDetail({ paper }: { paper: ResearchPaperRow }) {
  return (
    <div className="space-y-2 font-mono text-xs">
      <Row label="arXiv ID" value={paper.arxiv_id} />
      <Row label="Ingested" value={new Date(paper.ingested_at).toLocaleString()} />
      <div>
        <p className="mb-1 text-muted-foreground uppercase">Abstract</p>
        <p className="whitespace-pre-wrap leading-relaxed">{paper.abstract}</p>
      </div>
    </div>
  );
}

function ConcernDetail({ concern }: { concern: PipelineConcern }) {
  return (
    <div className="space-y-2 font-mono text-xs">
      <div>
        <Row label="Interval" value={`every ${Math.round(concern.interval_seconds / 60)} min`} />
        <Row
          label="Last ran"
          value={concern.last_run_at ? new Date(concern.last_run_at).toLocaleString() : 'never'}
        />
        <Row label="Status" value={concern.is_due ? 'due — runs next cron tick' : 'idle'} />
      </div>
      <p className="pt-2 leading-relaxed text-muted-foreground">
        {CONCERN_DESCRIPTIONS[concern.concern] ?? 'No description available.'}
      </p>
    </div>
  );
}

const CONCERN_TITLES: Record<string, string> = {
  ingest: 'Data ingestion',
  research: 'Research cycle',
  paper: 'Paper trading',
  llm_ingestion: 'LLM paper ingestion',
};

function titleFor(target: DetailTarget): string {
  if (target.kind === 'strategy') return target.id;
  if (target.kind === 'job') return `${target.job.family ?? 'Job'} backtest — ${target.job.symbol ?? '—'}`;
  if (target.kind === 'concern') return CONCERN_TITLES[target.concern.concern] ?? target.concern.concern;
  return target.paper.title;
}

/** One shared modal for every "click a row for more" interaction across
 * LiveActivity -- strategy/mutation rows fetch full detail via GET
 * /strategies/{id} (verdict/score/PBO/DSR/lineage, all real per Prompt
 * 5/7); in-flight job and paper rows just format the data the feed
 * already has in hand, since there's no separate detail endpoint worth
 * adding for either. */
export function DetailModal({ target, onClose }: DetailModalProps) {
  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open: boolean) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{target ? titleFor(target) : ''}</DialogTitle>
        </DialogHeader>
        {target?.kind === 'strategy' && <StrategyDetail id={target.id} />}
        {target?.kind === 'job' && <JobDetail job={target.job} />}
        {target?.kind === 'paper' && <PaperDetail paper={target.paper} />}
        {target?.kind === 'concern' && <ConcernDetail concern={target.concern} />}
      </DialogContent>
    </Dialog>
  );
}
