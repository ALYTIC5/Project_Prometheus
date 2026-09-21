import type {
  BenchmarkCurvePoint,
  BuildingWithCount,
  ClustersResponse,
  ExperimentDetail,
  ExperimentRow,
  PaperTradingResponse,
  PipelineStatusResponse,
  QueueStatus,
  ResearchPaperRow,
  ScoreboardResponse,
  StrategyRow,
  ViolationRow,
  WorldState,
} from './types';

// Empty string is a deliberate, valid value (production: frontend and API
// share one origin, so relative paths like "/world/state" are correct) --
// `??` rather than `||` so it isn't mistaken for "unset" and overridden.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function fetchWorldState(): Promise<WorldState> {
  const res = await fetch(`${API_BASE}/world/state`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`World state fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchBuildings(): Promise<{ buildings: BuildingWithCount[]; total: number }> {
  const res = await fetch(`${API_BASE}/buildings/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Buildings fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchScoreboard(): Promise<ScoreboardResponse> {
  const res = await fetch(`${API_BASE}/scoreboard/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Scoreboard fetch failed: ${res.status}`);
  return res.json();
}

// --- PROMPT S: plain dashboard endpoints ------------------------------

export async function fetchBenchmarkCurve(): Promise<BenchmarkCurvePoint[]> {
  const res = await fetch(`${API_BASE}/world/drilldown/benchmark/current`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Benchmark curve fetch failed: ${res.status}`);
  const body = (await res.json()) as { curve: BenchmarkCurvePoint[] };
  return body.curve;
}

export async function fetchStrategies(): Promise<{ strategies: StrategyRow[]; total: number }> {
  const res = await fetch(`${API_BASE}/strategies/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Strategies fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchExperiments(): Promise<{ experiments: ExperimentRow[]; total: number }> {
  const res = await fetch(`${API_BASE}/experiments/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Experiments fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchExperimentDetail(experimentId: string): Promise<ExperimentDetail> {
  const res = await fetch(`${API_BASE}/experiments/${experimentId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Experiment detail fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchQueueStatus(): Promise<QueueStatus> {
  const res = await fetch(`${API_BASE}/queue/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Queue status fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchViolations(): Promise<{ violations: ViolationRow[]; total: number }> {
  const res = await fetch(`${API_BASE}/violations/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Violations fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchPipelineStatus(): Promise<PipelineStatusResponse> {
  const res = await fetch(`${API_BASE}/pipeline/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Pipeline status fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchResearchPapers(): Promise<{ papers: ResearchPaperRow[]; total: number }> {
  const res = await fetch(`${API_BASE}/research-papers/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Research papers fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchPaperTrading(): Promise<PaperTradingResponse> {
  const res = await fetch(`${API_BASE}/paper/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Paper trading fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchClusters(): Promise<ClustersResponse> {
  const res = await fetch(`${API_BASE}/clusters/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Clusters fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchStrategyDetail(strategyId: string): Promise<StrategyRow> {
  const res = await fetch(`${API_BASE}/strategies/${strategyId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Strategy detail fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchDrilldown(
  entityType: string,
  entityId: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/world/drilldown/${entityType}/${entityId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Drilldown fetch failed: ${res.status}`);
  return res.json();
}

export function createWorldSocket(onMessage: (state: WorldState) => void): WebSocket {
  // API_BASE === "" means same-origin (production); derive ws(s):// from
  // the current page instead of blindly replacing a "http" substring that
  // won't exist in an empty string.
  const wsBase = API_BASE === '' ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}` : API_BASE.replace('http', 'ws');
  const ws = new WebSocket(`${wsBase}/world/deltas`);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'world_update') {
        onMessage(msg.data as WorldState);
      }
    } catch {
      // ignore parse errors
    }
  };
  return ws;
}
