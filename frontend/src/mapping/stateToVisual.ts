/**
 * The single source of visual truth (WORLD_CONSTITUTION.md's W2). Every
 * pure function here maps a real backend state to a visual descriptor.
 * If a visual decision is made anywhere else in the codebase, that is a bug.
 *
 * SCOPE NOTE: `frontend/src/sprites/registry.ts`'s `MANIFEST` already IS the
 * one source of truth for BUILDING construction-phase visuals -- it
 * predates this file, is the actual renderer implementation, and is
 * cross-referenced with the Python atlas pipeline (tools/art/pack_atlas.py's
 * `PROCEDURAL_BY_PHASE` mirror, checked by `verify_atlas.py`). Retrofitting
 * that already-working, already-verified system into this file would be
 * pure regression risk for zero behaviour change, so `mapBuildingStateToVisual`
 * below is a fresh implementation of the same semantic mapping (satisfying
 * this file's job of documenting the decision) but is NOT wired to replace
 * registry.ts's MANIFEST as the renderer's actual data source.
 *
 * HONESTY NOTE: every mapping below except `mapBuildingStateToVisual`'s
 * phase handling operates on a backend field that does not exist yet
 * (strategy_families, strategies, validation_results, paper_trades,
 * regime_classification, component_registry -- see docs/WORLD_MAPPING.md).
 * These functions are pure and fully tested against FIXTURE inputs per
 * W2.3's own instruction ("render every enum value from fixture snapshots")
 * -- they are correct and ready, but are not currently called with live
 * data anywhere, because there is no live data of these kinds. Wire each
 * one in when its owning prompt makes the corresponding entity real.
 *
 * No randomness anywhere in this file -- every function is a pure function
 * of its input, satisfying the "same WorldSnapshot -> identical visuals"
 * property this file's tests enforce.
 */

// ---------------------------------------------------------------------------
// Family / TEMPLE (strategy_families table -- Prompt 4, not real yet)
// ---------------------------------------------------------------------------

export type FamilyState = 'HEALTHY' | 'QUARANTINED' | 'DORMANT' | 'RETIRED';

export interface TempleVisual {
  state: FamilyState;
  /** Feature flags, not a free-text description -- easy to assert on in
   * tests (e.g. "no feature appears under two different states"). */
  features: readonly string[];
}

const TEMPLE_VISUALS: Record<FamilyState, readonly string[]> = {
  HEALTHY: ['lights-on', 'construction-activity', 'agents-present'],
  QUARANTINED: ['chains', 'guards', 'sealed-gate', 'warning-pulse'],
  DORMANT: ['overgrown', 'dark', 'sleeping'],
  RETIRED: ['ruins'],
};

export function mapFamilyStateToVisual(state: FamilyState): TempleVisual {
  return { state, features: TEMPLE_VISUALS[state] };
}

// ---------------------------------------------------------------------------
// Strategy / HERO (strategies table -- Prompt 4, not real yet)
// ---------------------------------------------------------------------------

export type StrategyState = 'PROMISING' | 'VALIDATED' | 'CHAMPION' | 'RETIRED' | 'REJECTED';

export type HeroLocation = 'DISTRICT' | 'CHAMPION_TEMPLE' | 'ARENA' | 'HALL_OF_LEGENDS' | 'UNDERWORLD';

export interface HeroVisual {
  state: StrategyState;
  location: HeroLocation;
  /** Explicit, not folded into `features`, because "no crown" is a named
   * honesty rule (W1.5 verify #2) -- a reviewer should be able to assert
   * `hasCrown === false` directly rather than infer it from an absence. */
  hasCrown: boolean;
  features: readonly string[];
}

const HERO_VISUALS: Record<StrategyState, Omit<HeroVisual, 'state'>> = {
  // RISING_HERO: halo + upward particles, explicitly NOT crowned and NOT
  // inside the champion temple -- PROMISING must read as unvalidated.
  PROMISING: { location: 'DISTRICT', hasCrown: false, features: ['halo', 'upward-particles'] },
  VALIDATED: { location: 'ARENA', hasCrown: false, features: ['formal-banner', 'arena-eligible'] },
  CHAMPION: { location: 'CHAMPION_TEMPLE', hasCrown: true, features: ['throne'] },
  RETIRED: { location: 'HALL_OF_LEGENDS', hasCrown: false, features: ['statue'] },
  REJECTED: { location: 'UNDERWORLD', hasCrown: false, features: ['tombstone', 'cause-of-death'] },
};

export function mapStrategyStateToVisual(state: StrategyState): HeroVisual {
  return { state, ...HERO_VISUALS[state] };
}

// ---------------------------------------------------------------------------
// Building (CONSTRUCTION_MANIFEST -- REAL today; see scope note above)
// ---------------------------------------------------------------------------

export type BuildingPhase = 'PLANNED' | 'SCAFFOLDING' | 'FOUNDATION' | 'ACTIVE' | 'DAMAGED' | 'SEALED' | 'OVERGROWN';

export interface BuildingSignals {
  phase: BuildingPhase;
  /** Real field (Structure.metrics.queue_depth) -- always 0 today, no jobs
   * table exists yet (Prompt 4). */
  queueDepth: number;
  /** oracle-only. Pending validation_results rows. Does not exist yet
   * (Prompt 5) -- undefined until then. */
  validationBacklog?: number;
  /** harbour-only. Paper-vs-live execution divergence flag. Does not exist
   * yet (Prompt 8) -- undefined until then. */
  executionDivergence?: boolean;
  /** vault/guardian-only. A real risk-limit breach. Does not exist yet
   * (risk system is env-var limits only today, Law 4) -- undefined until
   * a breach-detection signal exists. */
  riskBreach?: boolean;
}

export interface BuildingVisual {
  phase: BuildingPhase;
  busy: boolean;
  congested: boolean;
  warning: boolean;
  blocking: boolean;
}

/**
 * `queueBusyThreshold` is REQUIRED, no default -- CLAUDE.md: "inventing
 * numeric thresholds is how the second blueprint went wrong." queue_depth
 * is always 0 today (no jobs table), so any specific number here would be
 * a pure guess; the caller (once real queue data and product input on what
 * "busy" means both exist) must supply it explicitly.
 */
export function mapBuildingStateToVisual(signals: BuildingSignals, queueBusyThreshold: number): BuildingVisual {
  return {
    phase: signals.phase,
    busy: signals.queueDepth >= queueBusyThreshold,
    congested: (signals.validationBacklog ?? 0) > 0,
    warning: signals.executionDivergence === true,
    blocking: signals.riskBreach === true,
  };
}

// ---------------------------------------------------------------------------
// Regime -> Climate (regime_classification table -- Prompt 5, not real yet.
// climate.regime is hardcoded "unknown" today, see prometheus/world/
// projection.py's ClimateState() default.)
// ---------------------------------------------------------------------------

export type Regime = 'BEAR' | 'BULL' | 'HIGH_VOL' | 'LOW_VOL' | 'TRENDING' | 'RANGING' | 'CRISIS' | 'UNKNOWN';

export interface ClimateVisual {
  regime: Regime;
  ambient: 'CALM' | 'STORM' | 'EMERGENCY';
  features: readonly string[];
  /** 0-1, lower means less agent/world activity -- reduced, not fabricated:
   * only BEAR/CRISIS have a specified reduction, everything else is 1
   * (no basis to invent a number for regimes the source spec didn't cover). */
  activityMultiplier: number;
}

// Only BEAR and CRISIS have a source-specified visual. Every other regime
// (including UNKNOWN, the only value ever actually seen today) gets a
// neutral, undecorated default rather than an invented one -- there is no
// design input for what BULL/HIGH_VOL/LOW_VOL/TRENDING/RANGING should look
// like, so this file does not guess.
const CLIMATE_VISUALS: Record<Regime, Omit<ClimateVisual, 'regime'>> = {
  BEAR: { ambient: 'STORM', features: ['rain', 'darker-ambient'], activityMultiplier: 0.6 },
  CRISIS: { ambient: 'EMERGENCY', features: ['earthquake', 'emergency-activity'], activityMultiplier: 1 },
  BULL: { ambient: 'CALM', features: [], activityMultiplier: 1 },
  HIGH_VOL: { ambient: 'CALM', features: [], activityMultiplier: 1 },
  LOW_VOL: { ambient: 'CALM', features: [], activityMultiplier: 1 },
  TRENDING: { ambient: 'CALM', features: [], activityMultiplier: 1 },
  RANGING: { ambient: 'CALM', features: [], activityMultiplier: 1 },
  UNKNOWN: { ambient: 'CALM', features: [], activityMultiplier: 1 },
};

export function mapRegimeToClimate(regime: Regime): ClimateVisual {
  return { regime, ...CLIMATE_VISUALS[regime] };
}

// ---------------------------------------------------------------------------
// Component verdict (component_registry table -- Prompt 6, not real yet.
// Structure.verdict exists as a real field, always null today.)
// ---------------------------------------------------------------------------

export type ComponentVerdict = 'UNPROVEN' | 'VALUABLE' | 'NEUTRAL' | 'HARMFUL';

export interface ComponentVisual {
  verdict: ComponentVerdict;
  shrineGrowth: 'GROWING' | 'STABLE' | 'NEGLECTED' | 'NONE';
}

const COMPONENT_VISUALS: Record<ComponentVerdict, ComponentVisual['shrineGrowth']> = {
  VALUABLE: 'GROWING',
  NEUTRAL: 'STABLE',
  HARMFUL: 'NEGLECTED',
  UNPROVEN: 'NONE',
};

export function mapComponentVerdictToVisual(verdict: ComponentVerdict): ComponentVisual {
  return { verdict, shrineGrowth: COMPONENT_VISUALS[verdict] };
}

// ---------------------------------------------------------------------------
// Diversification -> alliance link (portfolio correlation -- Prompt 8, not
// real yet)
// ---------------------------------------------------------------------------

export type AllianceLink = 'BRIDGE' | 'TENSION' | 'MERGED' | 'NONE';

/**
 * `correlation` is a real-shaped input (-1..1, Pearson correlation between
 * two families' returns) -- thresholds for "complementary" vs "redundant"
 * are not specified by the source prompt and are not invented here; the
 * function documents the open question rather than picking numbers.
 */
export function mapDiversificationToAllianceVisual(correlation: number, complementaryBelow: number, redundantAbove: number): AllianceLink {
  if (correlation < complementaryBelow) return 'BRIDGE';
  if (correlation > redundantAbove) return 'TENSION';
  return 'NONE';
}
