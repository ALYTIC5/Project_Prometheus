export interface Climate {
  regime: string;
  volatility_percentile: number;
  trend_strength: number;
  crisis_flag: boolean;
  market_open: boolean;
}

export interface PopulationByStatus {
  champion: number;
  promising: number;
  experimental: number;
  regime_specialist: number;
  dormant: number;
  quarantined: number;
  retired: number;
}

export interface District {
  id: string;
  name: string;
  archetype: string;
  population_by_status: PopulationByStatus;
  health: number;
  activity: number;
  portfolio_weight: number;
  building_state: string;
  alert_flags: string[];
}

export interface Structure {
  id: string;
  kind: string;
  construction_phase: string;
  load: number;
  queue_depth: number;
  status: string;
  verdict: string | null;
  description: string | null;
  prompt_built: number | null;
}

export interface WorldEvent {
  type: string;
  subject_id: string;
  severity: string;
  timestamp: string;
  drill_down_url: string | null;
  message: string | null;
}

export interface BenchmarkMetrics {
  equity: number;
  return_pct: number;
  sharpe: number;
  max_drawdown: number;
}

export interface VsBenchmark {
  excess_return: number;
  excess_sharpe: number;
  winning: boolean | null;
}

export interface Treasury {
  total_equity: number;
  allocation_by_family: Record<string, number>;
  drawdown: number;
  paper_pnl_today: number;
  benchmark: BenchmarkMetrics;
  vs_benchmark: VsBenchmark;
  infra_cost_mtd: number;
  llm_cost_mtd: number;
}

export interface LawCompliance {
  law_id: number;
  name: string;
  compliant: boolean;
  last_violation: string | null;
  summary: string;
}

export interface Scoreboard {
  starting_capital: number;
  currency: string;
  system_value: number | null;
  benchmark_value: number;
  excess: number | null;
  infra_cost_to_date: number;
  net_after_costs: number | null;
  verdict: string;
}

export interface BuildProgress {
  total: number;
  active: number;
  scaffolding: number;
}

/** prometheus/world/entities.py's Agent -- one per claimed `jobs` row
 * (Prompt 4). Real and populated as of migration 0007; previously this
 * repo's WorldState.agents field was typed any[] with a comment claiming
 * no backend source existed yet, which stopped being true once jobs went
 * live. */
export interface Agent {
  id: string;
  role: string;
  from_location: string;
  to_location: string;
  progress: number;
  experiment_id: string | null;
}

/** GET /scoreboard/'s response — a superset of the Scoreboard model,
 * flattened with verdict_label plus the benchmark/vs_benchmark objects. */
export interface ScoreboardResponse extends Scoreboard {
  verdict_label: string;
  benchmark: BenchmarkMetrics;
  vs_benchmark: VsBenchmark;
  build_progress: BuildProgress;
}

/** W0 normalized entity contract (prometheus/world/entities.py's
 * WorldEntity). As of Prompt 4, BUILDING, GOD, HERO (one per `strategies`
 * row) and EXPERIMENT (one per `experiments` row) are populated -- the
 * rest (TEMPLE, AGENT, ARENA_MATCH, RESEARCH_SOURCE, PORTFOLIO, ALERT,
 * REGIME, ARCHIVE_ENTRY) still have no real backend source and will not
 * appear until their owning prompt builds the table. `state` is verbatim
 * from the backend; there is deliberately no `visual_state` on the wire --
 * that mapping is frontend-only, one file (see docs/WORLD_MAPPING.md), not
 * built yet. */
export type WorldEntityType =
  | 'GOD' | 'TEMPLE' | 'HERO' | 'AGENT' | 'BUILDING' | 'EXPERIMENT'
  | 'ARENA_MATCH' | 'RESEARCH_SOURCE' | 'PORTFOLIO' | 'ALERT' | 'REGIME' | 'ARCHIVE_ENTRY';

export interface EntityLocation {
  zone: string;
  x: number;
  y: number;
}

export interface WorldEntity {
  entity_id: string;
  entity_type: WorldEntityType;
  source_entity_id: string;
  parent_entity_id: string | null;
  state: string;
  health: number;
  activity: number;
  location: EntityLocation;
  metrics: Record<string, unknown>;
  reasons: string[];
  evidence_refs: string[];
}

export interface BuildingLocation {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Building {
  id: string;
  kind: string;
  description: string;
  prompt: number | null;
  phase: string;
  location: BuildingLocation;
  color: string;
  agent_roles: string[];
  activates_on: string[];
}

export interface WorldState {
  tick: number;
  generated_at: string;
  source_data_version: string | null;
  climate: Climate;
  districts: District[];
  agents: Agent[];
  structures: Structure[];
  entities: WorldEntity[];
  events: WorldEvent[];
  treasury: Treasury;
  laws: LawCompliance[];
  scoreboard: Scoreboard;
  build_progress: BuildProgress;
}

// --- PROMPT S: plain dashboard types -----------------------------------

export interface BenchmarkCurvePoint {
  date: string;
  equity: number;
}

/** GET /buildings/'s per-building payload, now including row_count (the
 * sum of collect_row_counts() across every table the building activates
 * on -- see api/routes/buildings.py). */
export interface BuildingWithCount extends Building {
  row_count: number;
}

export interface StrategyRow {
  id: string;
  family: string;
  spec: Record<string, unknown>;
  status: string;
  created_at: string;
}

export interface DecisionPayload {
  decision: string;
  reason?: string;
  reason_codes?: string[];
  [key: string]: unknown;
}

/** GET /experiments/'s list-item shape. hypothesis/parent_experiment_id
 * are migration 0006 columns, null for anything created before that
 * migration or run without them supplied. `decision` is the latest
 * decisions row for this experiment (Law 6: there can be more than one;
 * latest wins), null if none has been recorded yet. */
export interface ExperimentRow {
  id: string;
  status: string;
  payload: Record<string, unknown>;
  hypothesis: string | null;
  parent_experiment_id: string | null;
  created_at: string;
  decision: DecisionPayload | null;
}

export interface ExperimentResultRow {
  payload: Record<string, unknown>;
  created_at: string;
}

export interface ExperimentDecisionRow {
  decision: DecisionPayload;
  created_at: string;
}

/** GET /experiments/{id}'s full shape -- ExperimentRow plus its real
 * results/decisions rows. */
export interface ExperimentDetail extends ExperimentRow {
  results: ExperimentResultRow[];
  decisions: ExperimentDecisionRow[];
}

export interface InFlightJob {
  id: string;
  kind: string;
  agent_role: string;
  current_stage: string;
  next_stage: string;
  progress_pct: number;
  experiment_id: string | null;
}

/** GET /queue/'s shape. failed_pending_count is the honest proxy for
 * "failed jobs" -- there is no `failed` status (see experiments/queue.py):
 * a failed job is retried back to pending, or moved to jobs_dead_letter. */
export interface QueueStatus {
  pending_by_kind: Record<string, number>;
  in_flight: InFlightJob[];
  dead_letter_count: number;
  failed_pending_count: number;
}

export interface ViolationRow {
  id: number;
  violation_type: string;
  experiment_id: string | null;
  detail: Record<string, unknown>;
  detected_at: string;
}
