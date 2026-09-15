import type { ScoreboardResponse } from '../types';

interface BenchmarkStripProps {
  scoreboard: ScoreboardResponse | null;
}

/** Fixed, non-dismissible header strip (WORLD_CONSTITUTION.md's W1.2 / Law
 * 8): every result is measured against the real €1,000 buy-and-hold
 * benchmark. This is a UI requirement, not a preference -- it has no close
 * button and no toggle. All values are the real scoreboard fields; "€—"
 * means the real value is genuinely null (no strategy has ever paper
 * traded), never a fabricated placeholder number. */
export function BenchmarkStrip({ scoreboard }: BenchmarkStripProps) {
  const system = scoreboard?.system_value != null ? `€${scoreboard.system_value.toFixed(0)}` : '€—';
  const benchmark = scoreboard ? `€${scoreboard.benchmark_value.toFixed(0)}` : '€—';
  const net = scoreboard?.net_after_costs != null ? `€${scoreboard.net_after_costs.toFixed(0)}` : '€—';
  const verdict = scoreboard?.verdict_label ?? scoreboard?.verdict ?? 'NOT_STARTED';

  return (
    <div
      role="status"
      aria-label="Benchmark comparison -- Law 8: every result is measured against buy-and-hold, always"
      className="fixed top-0 right-0 left-0 z-40 flex items-center justify-center gap-2 border-b border-border bg-background/95 px-4 py-2 font-mono text-xs text-foreground sm:gap-4"
    >
      <span>
        Your system: <strong>{system}</strong>
      </span>
      <span aria-hidden="true" className="text-muted-foreground">
        |
      </span>
      <span>
        Just holding: <strong>{benchmark}</strong>
      </span>
      <span aria-hidden="true" className="text-muted-foreground">
        |
      </span>
      <span>
        Net of costs: <strong>{net}</strong>
      </span>
      <span aria-hidden="true" className="text-muted-foreground">
        |
      </span>
      <span className="font-semibold">{verdict}</span>
    </div>
  );
}
