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
 *
 * PROMPT S: every hook takes an optional intervalMs override instead of
 * forking this module for the plain dashboard, which polls at its own
 * documented 10s. The world view's call sites are unchanged (still 5s).
 */

import { useQuery } from '@tanstack/react-query';
import {
  fetchBenchmarkCurve,
  fetchBuildings,
  fetchClusters,
  fetchExperimentDetail,
  fetchExperiments,
  fetchExperimentsScatter,
  fetchPaperTrading,
  fetchPipelineStatus,
  fetchQueueStatus,
  fetchResearchPapers,
  fetchScoreboard,
  fetchStrategies,
  fetchStrategyDetail,
  fetchViolations,
  fetchWorldState,
} from '../api';

const POLL_INTERVAL_MS = 5000;

// Each hook takes an optional override -- the world view's call sites pass
// nothing (unchanged 5s behavior); the plain dashboard (PROMPT S) passes
// 10000, its own documented cadence, without forking this module.
export function useWorldStateQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['world-state'],
    queryFn: fetchWorldState,
    refetchInterval: intervalMs,
  });
}

export function useBuildingsQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['buildings'],
    queryFn: fetchBuildings,
    refetchInterval: intervalMs,
  });
}

export function useScoreboardQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['scoreboard'],
    queryFn: fetchScoreboard,
    refetchInterval: intervalMs,
  });
}

// --- PROMPT S: plain dashboard hooks ---------------------------------

export function useBenchmarkCurveQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['benchmark-curve'],
    queryFn: fetchBenchmarkCurve,
    refetchInterval: intervalMs,
  });
}

export function useStrategiesQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: fetchStrategies,
    refetchInterval: intervalMs,
  });
}

export function useExperimentsQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['experiments'],
    queryFn: fetchExperiments,
    refetchInterval: intervalMs,
  });
}

export function useExperimentsScatterQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['experiments-scatter'],
    queryFn: fetchExperimentsScatter,
    refetchInterval: intervalMs,
  });
}

export function useQueueQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['queue'],
    queryFn: fetchQueueStatus,
    refetchInterval: intervalMs,
  });
}

export function useViolationsQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['violations'],
    queryFn: fetchViolations,
    refetchInterval: intervalMs,
  });
}

// On-demand, not polled -- fetched only when a row is expanded.
export function useExperimentDetailQuery(experimentId: string | null) {
  return useQuery({
    queryKey: ['experiment-detail', experimentId],
    queryFn: () => fetchExperimentDetail(experimentId as string),
    enabled: experimentId !== null,
  });
}

export function usePipelineStatusQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['pipeline-status'],
    queryFn: fetchPipelineStatus,
    refetchInterval: intervalMs,
  });
}

export function useResearchPapersQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['research-papers'],
    queryFn: fetchResearchPapers,
    refetchInterval: intervalMs,
  });
}

export function usePaperTradingQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['paper-trading'],
    queryFn: fetchPaperTrading,
    refetchInterval: intervalMs,
  });
}

export function useClustersQuery(intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ['clusters'],
    queryFn: fetchClusters,
    refetchInterval: intervalMs,
  });
}

// On-demand, not polled -- same posture as useExperimentDetailQuery, fetched
// only when the detail modal opens for a given strategy.
export function useStrategyDetailQuery(strategyId: string | null) {
  return useQuery({
    queryKey: ['strategy-detail', strategyId],
    queryFn: () => fetchStrategyDetail(strategyId as string),
    enabled: strategyId !== null,
  });
}
