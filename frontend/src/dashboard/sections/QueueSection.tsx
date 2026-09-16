'use client';

import { useQueueQuery } from '../../data/queries';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

/** SECTION 6 -- QUEUE. Real data, GET /queue/ (new route, PROMPT S) over
 * experiments/queue.py's jobs table (Prompt 4, already built). "Failed
 * jobs" is failed_pending_count -- the honest proxy: there is no `failed`
 * status, a failed job is retried-to-pending or dead-lettered. */
export function QueueSection() {
  const { data, isLoading } = useQueueQuery(DASHBOARD_POLL_MS);
  const pendingByKind = Object.entries(data?.pending_by_kind ?? {});
  const inFlight = data?.in_flight ?? [];
  const isEmpty =
    !isLoading &&
    pendingByKind.length === 0 &&
    inFlight.length === 0 &&
    (data?.dead_letter_count ?? 0) === 0 &&
    (data?.failed_pending_count ?? 0) === 0;

  return (
    <Section
      storageKey="queue"
      title="Queue"
      isEmpty={isEmpty}
      emptyLabel="Arena — no job has ever been enqueued (experiments/queue.py)"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-4 font-mono text-xs">
          <div className="flex gap-6">
            <span>
              Failed (pending retry): <strong>{data?.failed_pending_count ?? 0}</strong>
            </span>
            <span>
              Dead letter: <strong>{data?.dead_letter_count ?? 0}</strong>
            </span>
            <span>
              In flight: <strong>{inFlight.length}</strong>
            </span>
          </div>

          {pendingByKind.length > 0 && (
            <div>
              <p className="pb-1 text-muted-foreground uppercase">Pending depth by kind</p>
              <table className="w-full max-w-sm border-collapse text-left">
                <tbody>
                  {pendingByKind.map(([kind, n]) => (
                    <tr key={kind} className="border-b border-border/50">
                      <td className="py-1 pr-4">{kind}</td>
                      <td className="py-1">{n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {inFlight.length > 0 && (
            <div className="overflow-x-auto">
              <p className="pb-1 text-muted-foreground uppercase">Running</p>
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-border text-muted-foreground uppercase">
                    <th className="py-1 pr-4 font-medium">Job</th>
                    <th className="py-1 pr-4 font-medium">Kind</th>
                    <th className="py-1 pr-4 font-medium">Agent</th>
                    <th className="py-1 pr-4 font-medium">Stage</th>
                    <th className="py-1 pr-4 font-medium">Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {inFlight.map((job) => (
                    <tr key={job.id} className="border-b border-border/50">
                      <td className="py-1 pr-4">{job.id}</td>
                      <td className="py-1 pr-4">{job.kind}</td>
                      <td className="py-1 pr-4">{job.agent_role}</td>
                      <td className="py-1 pr-4 text-muted-foreground">
                        {job.current_stage} → {job.next_stage}
                      </td>
                      <td className="py-1 pr-4">{(job.progress_pct * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
