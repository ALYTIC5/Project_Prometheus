'use client';

import { BenchmarkStrip } from '../components/BenchmarkStrip';
import type { ScoreboardResponse, WorldState } from '../types';

interface DashboardHeaderProps {
  scoreboard: ScoreboardResponse | null;
  world: WorldState | null;
  isError: boolean;
}

/** The always-visible header strip (S: "never dismissible"). Reuses
 * BenchmarkStrip exactly as the world view does -- it already renders
 * "Your system | Just holding | Net of costs | VERDICT" fixed at the top,
 * so this only adds the second line the plain-dashboard spec asks for:
 * build progress, last tick, and an API health dot. Positioned as its own
 * fixed row directly beneath BenchmarkStrip rather than editing that
 * component (Law 8: it is deliberately not a shared layout concern). */
export function DashboardHeader({ scoreboard, world, isError }: DashboardHeaderProps) {
  return (
    <>
      <BenchmarkStrip scoreboard={scoreboard} />
      <div
        role="status"
        className="fixed top-9 right-0 left-0 z-40 flex items-center justify-center gap-3 border-b border-border bg-muted/50 px-4 py-1 font-mono text-[11px] text-muted-foreground"
      >
        <span>
          Build progress:{' '}
          {world ? `${world.build_progress.active}/${world.build_progress.total} systems online` : '—'}
        </span>
        <span aria-hidden="true">|</span>
        <span>
          Last tick: {world ? new Date(world.generated_at).toLocaleTimeString() : '—'}
        </span>
        <span aria-hidden="true">|</span>
        <span className="flex items-center gap-1.5">
          API
          <span
            aria-hidden="true"
            className={`inline-block h-2 w-2 rounded-full ${isError ? 'bg-red-500' : 'bg-emerald-500'}`}
          />
        </span>
      </div>
    </>
  );
}
