'use client';

import { useState } from 'react';
import { usePipelineStatusQuery } from '../data/queries';
import type { PipelineConcern } from '../types';
import { DetailModal, type DetailTarget } from './DetailModal';

const DASHBOARD_POLL_MS = 10000;

const CONCERN_LABELS: Record<string, string> = {
  ingest: 'Ingest',
  research: 'Research',
  paper: 'Paper',
  llm_ingestion: 'Papers',
};

function relativeTime(iso: string | null): string {
  if (iso === null) return 'never run';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function ConcernChip({ concern, onClick }: { concern: PipelineConcern; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded border border-border px-2 py-1 font-mono text-[11px] hover:bg-muted/40"
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          concern.is_due ? 'bg-amber-500' : 'bg-emerald-500'
        }`}
        title={concern.is_due ? 'due — runs next cron tick' : 'idle'}
      />
      <span className="font-semibold">{CONCERN_LABELS[concern.concern] ?? concern.concern}</span>
      <span className="text-muted-foreground">{relativeTime(concern.last_run_at)}</span>
    </button>
  );
}

/** Pipeline overview -- the worker's four cadence-gated concerns
 * (ingest/research/paper/llm_ingestion), each rendered as a clickable
 * chip reading GET /pipeline/ (worker_cadence, the same table
 * worker.py's own is_due() reads). Sits above LiveActivity's detail
 * feed: this answers "is the worker alive and what's it about to do
 * next", the feed answers "what has it actually produced". */
export function PipelineStatus() {
  const { data, isLoading, isError, error } = usePipelineStatusQuery(DASHBOARD_POLL_MS);
  const [target, setTarget] = useState<DetailTarget | null>(null);

  if (isError) {
    return (
      <div className="border-b border-border px-4 py-2 font-mono text-xs text-red-400">
        Pipeline status unavailable: {String(error)}
      </div>
    );
  }

  if (isLoading || !data) {
    return (
      <div className="border-b border-border px-4 py-2 font-mono text-xs text-muted-foreground">
        Loading pipeline status…
      </div>
    );
  }

  const { job_health: jobHealth, recent_failures: recentFailures } = data;

  return (
    <>
      {jobHealth.unhealthy && (
        <div
          className="border-b border-red-900 bg-red-950/80 px-4 py-2 font-mono text-[11px] text-red-200"
          title={recentFailures.map((f) => `${f.concern}/${f.exception_type} x${f.failure_count}`).join(', ')}
        >
          ⚠ {Math.round((jobHealth.failure_rate ?? 0) * 100)}% of jobs failed in the last{' '}
          {jobHealth.window_hours}h ({jobHealth.dead_lettered} of{' '}
          {jobHealth.dead_lettered + jobHealth.succeeded}) — see recent_failures below or
          worker_health in the DB.
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/10 px-4 py-2">
        <span className="font-mono text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
          Pipeline
        </span>
        {data.concerns.map((concern) => (
          <ConcernChip
            key={concern.concern}
            concern={concern}
            onClick={() => setTarget({ kind: 'concern', concern })}
          />
        ))}
      </div>
      <DetailModal target={target} onClose={() => setTarget(null)} />
    </>
  );
}
