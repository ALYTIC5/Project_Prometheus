/**
 * The one data adapter module (WORLD_CONSTITUTION.md's W0.3: "one data
 * adapter module, nothing else touches the network"). Components import
 * hooks from here, never `fetch`/`../api` directly.
 *
 * Polling cadence: WORLD_CONSTITUTION.md specifies tiers (1-5s critical,
 * 10-30s summaries, on-demand, event-driven) for data that doesn't exist
 * yet -- no jobs, no experiments, no alerts, nothing that actually changes
 * on a different cadence than anything else today. Buildings/scoreboard/
 * world-state are one page's needs with one real update frequency, so this
 * is honestly ONE tier (5s, matching the polling this replaces) rather than
 * fragmenting into cadences with no real justification. Revisit per-tier
 * cadences once Prompt 4+ produces data that actually warrants them.
 */

import { useQuery } from '@tanstack/react-query';
import { fetchBuildings, fetchScoreboard, fetchWorldState } from '../api';

const POLL_INTERVAL_MS = 5000;

export function useWorldStateQuery() {
  return useQuery({
    queryKey: ['world-state'],
    queryFn: fetchWorldState,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useBuildingsQuery() {
  return useQuery({
    queryKey: ['buildings'],
    queryFn: fetchBuildings,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useScoreboardQuery() {
  return useQuery({
    queryKey: ['scoreboard'],
    queryFn: fetchScoreboard,
    refetchInterval: POLL_INTERVAL_MS,
  });
}
