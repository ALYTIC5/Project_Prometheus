'use client';

import { useViolationsQuery } from '../data/queries';

const DASHBOARD_POLL_MS = 10000;

/** "Any RESEARCH_VIOLATION renders as a loud red banner at the top of the
 * page." Driven directly by GET /violations/ (real, Prompt 4) rather than
 * WorldState.laws' static compliant flag -- see LawsSection's note. Renders
 * nothing when there are no violations; never a quiet placeholder. */
export function ViolationsBanner() {
  const { data } = useViolationsQuery(DASHBOARD_POLL_MS);
  const violations = data?.violations ?? [];
  if (violations.length === 0) return null;

  const latest = violations[0];
  return (
    <div
      role="alert"
      className="border-b border-red-900 bg-red-600 px-4 py-2 text-center font-mono text-xs font-semibold text-white"
    >
      RESEARCH_VIOLATION: {violations.length} recorded -- latest {latest.violation_type} on
      experiment {latest.experiment_id ?? 'unknown'} at{' '}
      {new Date(latest.detected_at).toLocaleString()}
    </div>
  );
}
