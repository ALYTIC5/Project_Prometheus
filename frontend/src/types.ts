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

/** GET /scoreboard/'s response — a superset of the Scoreboard model,
 * flattened with verdict_label plus the benchmark/vs_benchmark objects. */
export interface ScoreboardResponse extends Scoreboard {
  verdict_label: string;
  benchmark: BenchmarkMetrics;
  vs_benchmark: VsBenchmark;
  build_progress: BuildProgress;
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
  agents: any[];
  structures: Structure[];
  events: WorldEvent[];
  treasury: Treasury;
  laws: LawCompliance[];
  scoreboard: Scoreboard;
  build_progress: BuildProgress;
}
