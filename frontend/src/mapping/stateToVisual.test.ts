import { describe, expect, it } from 'vitest';
import {
  mapBuildingStateToVisual,
  mapComponentVerdictToVisual,
  mapDiversificationToAllianceVisual,
  mapFamilyStateToVisual,
  mapRegimeToClimate,
  mapStrategyStateToVisual,
  type FamilyState,
  type Regime,
  type StrategyState,
} from './stateToVisual';

const FAMILY_STATES: FamilyState[] = ['HEALTHY', 'QUARANTINED', 'DORMANT', 'RETIRED'];
const STRATEGY_STATES: StrategyState[] = ['PROMISING', 'VALIDATED', 'CHAMPION', 'RETIRED', 'REJECTED'];
const REGIMES: Regime[] = ['BEAR', 'BULL', 'HIGH_VOL', 'LOW_VOL', 'TRENDING', 'RANGING', 'CRISIS', 'UNKNOWN'];

describe('determinism (W2.3): same input always produces identical output', () => {
  it('mapFamilyStateToVisual', () => {
    for (const state of FAMILY_STATES) {
      expect(mapFamilyStateToVisual(state)).toEqual(mapFamilyStateToVisual(state));
    }
  });

  it('mapStrategyStateToVisual', () => {
    for (const state of STRATEGY_STATES) {
      expect(mapStrategyStateToVisual(state)).toEqual(mapStrategyStateToVisual(state));
    }
  });

  it('mapRegimeToClimate', () => {
    for (const regime of REGIMES) {
      expect(mapRegimeToClimate(regime)).toEqual(mapRegimeToClimate(regime));
    }
  });

  it('mapBuildingStateToVisual', () => {
    const signals = { phase: 'ACTIVE' as const, queueDepth: 3 };
    expect(mapBuildingStateToVisual(signals, 10)).toEqual(mapBuildingStateToVisual(signals, 10));
  });
});

describe('fixture coverage (W2.3): every enum value renders a defined visual', () => {
  it('every FamilyState', () => {
    for (const state of FAMILY_STATES) {
      const visual = mapFamilyStateToVisual(state);
      expect(visual.features.length).toBeGreaterThan(0);
    }
  });

  it('every StrategyState', () => {
    for (const state of STRATEGY_STATES) {
      const visual = mapStrategyStateToVisual(state);
      expect(visual.location).toBeDefined();
      expect(typeof visual.hasCrown).toBe('boolean');
    }
  });

  it('every Regime', () => {
    for (const regime of REGIMES) {
      const visual = mapRegimeToClimate(regime);
      expect(visual.ambient).toBeDefined();
      expect(visual.activityMultiplier).toBeGreaterThan(0);
    }
  });
});

describe('honesty rules (W2.2)', () => {
  it('PROMISING is visually distinct from VALIDATED -- no shared feature, no shared crown/location', () => {
    const promising = mapStrategyStateToVisual('PROMISING');
    const validated = mapStrategyStateToVisual('VALIDATED');
    const overlap = promising.features.filter((f) => validated.features.includes(f));
    expect(overlap).toEqual([]);
    expect(promising.location).not.toBe(validated.location);
  });

  it('PROMISING never has a crown and never renders inside the champion temple', () => {
    const rising = mapStrategyStateToVisual('PROMISING');
    expect(rising.hasCrown).toBe(false);
    expect(rising.location).not.toBe('CHAMPION_TEMPLE');
  });

  it('only CHAMPION has a crown -- uncertainty stays visible for every other state', () => {
    for (const state of STRATEGY_STATES) {
      const visual = mapStrategyStateToVisual(state);
      expect(visual.hasCrown).toBe(state === 'CHAMPION');
    }
  });

  it('REJECTED carries a visible cause-of-death feature, never dressed as a win', () => {
    const rejected = mapStrategyStateToVisual('REJECTED');
    expect(rejected.features).toContain('cause-of-death');
    expect(rejected.hasCrown).toBe(false);
  });

  it('no two FamilyStates share a feature (QUARANTINED reads as blocked, not as a lesser HEALTHY)', () => {
    const seen = new Map<string, FamilyState>();
    for (const state of FAMILY_STATES) {
      for (const feature of mapFamilyStateToVisual(state).features) {
        const owner = seen.get(feature);
        expect(owner, `feature "${feature}" appears under both ${owner} and ${state}`).toBeUndefined();
        seen.set(feature, state);
      }
    }
  });

  it('regimes with no source-specified visual get a neutral default, not an invented one', () => {
    for (const regime of ['BULL', 'HIGH_VOL', 'LOW_VOL', 'TRENDING', 'RANGING'] as Regime[]) {
      const visual = mapRegimeToClimate(regime);
      expect(visual.ambient).toBe('CALM');
      expect(visual.features).toEqual([]);
      expect(visual.activityMultiplier).toBe(1);
    }
  });

  it('BEAR and CRISIS reduce or hold activity, never increase it above baseline', () => {
    expect(mapRegimeToClimate('BEAR').activityMultiplier).toBeLessThanOrEqual(1);
    expect(mapRegimeToClimate('CRISIS').activityMultiplier).toBeLessThanOrEqual(1);
  });
});

describe('mapBuildingStateToVisual (the one real mapping today)', () => {
  it('busy is only true at or above the caller-supplied threshold -- no invented default', () => {
    const signals = { phase: 'ACTIVE' as const, queueDepth: 5 };
    expect(mapBuildingStateToVisual(signals, 10).busy).toBe(false);
    expect(mapBuildingStateToVisual(signals, 5).busy).toBe(true);
  });

  it('congested/warning/blocking stay false when the underlying signal is absent (honest default)', () => {
    const visual = mapBuildingStateToVisual({ phase: 'ACTIVE', queueDepth: 0 }, 10);
    expect(visual.congested).toBe(false);
    expect(visual.warning).toBe(false);
    expect(visual.blocking).toBe(false);
  });

  it('a real risk breach signal blocks the building', () => {
    const visual = mapBuildingStateToVisual({ phase: 'ACTIVE', queueDepth: 0, riskBreach: true }, 10);
    expect(visual.blocking).toBe(true);
  });
});

describe('mapComponentVerdictToVisual', () => {
  it('every verdict maps to a defined shrine state', () => {
    for (const verdict of ['UNPROVEN', 'VALUABLE', 'NEUTRAL', 'HARMFUL'] as const) {
      expect(mapComponentVerdictToVisual(verdict).shrineGrowth).toBeDefined();
    }
  });

  it('VALUABLE grows, HARMFUL neglects -- never the reverse', () => {
    expect(mapComponentVerdictToVisual('VALUABLE').shrineGrowth).toBe('GROWING');
    expect(mapComponentVerdictToVisual('HARMFUL').shrineGrowth).toBe('NEGLECTED');
  });
});

describe('mapDiversificationToAllianceVisual', () => {
  it('is a pure threshold function with no invented defaults baked in', () => {
    expect(mapDiversificationToAllianceVisual(-0.5, 0, 0.7)).toBe('BRIDGE');
    expect(mapDiversificationToAllianceVisual(0.9, 0, 0.7)).toBe('TENSION');
    expect(mapDiversificationToAllianceVisual(0.3, 0, 0.7)).toBe('NONE');
  });
});
