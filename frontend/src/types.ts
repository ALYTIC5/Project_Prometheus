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

/** GET /strategies/'s per-row shape. verdict/score/pbo/deflated_sharpe/
 * excess_return/excess_sharpe/reason_codes come from the strategy's
 * latest validation_results row (null/empty until Prompt 5's validator
 * has run against it, an honest "not yet validated" state, not missing
 * data). generation/parent are resolved server-side from the spec's own
 * parent_id chain (prometheus/api/routes/strategies.py's
 * _resolve_lineage) -- generation 0 and parent null both mean "no
 * traceable parent," which is the correct reading for a strategy that
 * really has none (grid-search seed) and one whose parent isn't in the
 * table (deleted, or predates this feature) alike. */
export interface StrategyRow {
  id: string;
  family: string;
  spec: Record<string, unknown>;
  status: string;
  created_at: string;
  /** Resolved server-side from universe_membership by the spec's symbol
   * (prometheus/api/routes/strategies.py's _enrich) -- null for a symbol
   * with no universe_membership row, an honest "unknown", not "crypto"
   * by default. */
  asset_class: string | null;
  verdict: string | null;
  score: number | null;
  pbo: number | null;
  deflated_sharpe: number | null;
  excess_return: number | null;
  excess_sharpe: number | null;
  reason_codes: string[];
  generation: number;
  parent: string | null;
  /** A short human label for the mutation that produced this strategy
   * ("tune fast_window", "swap family", "crossover", "LLM hypothesis"),
   * derived server-side from the creating experiment's real change_set
   * (prometheus/api/routes/strategies.py's _mutation_label) -- null for
   * a grid-search seed (no mutation) or before this strategy's creating
   * experiment has run yet. */
  mutation_label: string | null;
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
  // From the experiment's latest results row -- null on the
  // insufficient_data path, which writes a Decision but no Result.
  total_return_pct: number | null;
  benchmark_return_pct: number | null;
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
  /** Read straight off the job's own payload (every run_backtest job
   * carries its full spec) -- null only if a future job kind ever
   * ships a payload with no spec field. */
  family: string | null;
  symbol: string | null;
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

/** GET /pipeline/'s shape -- worker.py's own worker_cadence table, one
 * row per concern (ingest/research/paper/llm_ingestion). last_run_at/
 * next_due_at are null only for a concern that has never completed a
 * cycle yet (an honest "never run", not an error). */
export interface PipelineConcern {
  concern: string;
  interval_seconds: number;
  last_run_at: string | null;
  next_due_at: string | null;
  is_due: boolean;
}

export interface PipelineStatusResponse {
  concerns: PipelineConcern[];
}

/** GET /research-papers/'s shape -- PROMPT 9's daily arXiv ingestion. */
export interface ResearchPaperRow {
  id: number;
  arxiv_id: string;
  title: string;
  abstract: string;
  ingested_at: string;
}

/** GET /paper/'s shape -- the Harbour. One entry per CHAMPION-status
 * strategy (none today: every validated strategy so far is REJECT).
 * equity_curve is real mark-to-market from actual fills
 * (paper.reconciliation.compute_paper_equity_curve), not simulated. */
export interface PaperEquityPoint {
  date: string;
  equity: number;
}

export interface PaperOrderRow {
  id: string;
  symbol: string;
  side: string;
  qty: number;
  status: string;
  expected_price: number;
  avg_fill_price: number | null;
  filled_qty: number;
  submitted_at: string;
  filled_at: string | null;
}

export interface PaperFindingRow {
  id: number;
  finding_type: string;
  detail: Record<string, unknown>;
  detected_at: string;
}

export interface PaperChampion {
  strategy_id: string;
  family: string;
  symbol: string;
  equity_curve: PaperEquityPoint[];
  recent_orders: PaperOrderRow[];
  recent_findings: PaperFindingRow[];
}

export interface PaperTradingResponse {
  champions: PaperChampion[];
  total: number;
}

/** GET /clusters/'s shape -- the "100 strategies" prompt's own explicit
 * ask: real return-stream correlation clustering, so several near-
 * duplicate strategies (e.g. SMA/EMA/DEMA crossovers) don't get
 * mistaken for independent discoveries. Read-only, informational --
 * does not affect CHAMPION eligibility (see docs/DEFERRED.md). */
export interface ClusterMember {
  strategy_id: string | null;
  family: string | null;
  config_hash: string;
  is_representative: boolean;
  score: number | null;
  verdict: string | null;
}

export interface StrategyCluster {
  cluster_key: string;
  mean_pairwise_correlation: number;
  members: ClusterMember[];
}

export interface ClustersResponse {
  clusters: StrategyCluster[];
  total: number;
}
