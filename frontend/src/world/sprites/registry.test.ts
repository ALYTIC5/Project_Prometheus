import { describe, expect, it } from 'vitest';
import { classifyFootprint, resolvePropSprite, resolveSilhouette, resolveSprite } from './registry';

describe('classifyFootprint', () => {
  it('classifies 1x1 as TOWER, 2x2 as MEDIUM, 3x3 as LARGE', () => {
    expect(classifyFootprint(1, 1)).toBe('TOWER');
    expect(classifyFootprint(2, 2)).toBe('MEDIUM');
    expect(classifyFootprint(3, 3)).toBe('LARGE');
  });
});

describe('resolveSprite', () => {
  it('is always opaque-capable: no phase relies on partial fill alpha', () => {
    const phases = ['PLANNED', 'SCAFFOLDING', 'FOUNDATION', 'ACTIVE', 'DAMAGED', 'SEALED', 'OVERGROWN'] as const;
    for (const phase of phases) {
      const spec = resolveSprite('building', 'library', phase);
      expect(spec).not.toHaveProperty('fillAlpha');
    }
  });

  it('the monument always resolves to the ACTIVE spec regardless of phase argument', () => {
    const active = resolveSprite('monument', 'monument', 'ACTIVE');
    const sealed = resolveSprite('monument', 'monument', 'SEALED');
    expect(sealed).toEqual(active);
  });
});

describe('resolvePropSprite', () => {
  // SPRITE_SET is read once at module load from window.__SPRITE_SET__, so a
  // unit test can't flip it to 'production' without a module-reset dance
  // this file doesn't otherwise use (same reason resolveTerrainSprite has
  // no dedicated test either) -- this only covers the placeholder-mode
  // fallback every caller relies on when no manifest is loaded. Production
  // behaviour is verified by tools/art/build_r2_manifest.py's own output
  // review, not a unit test.
  it('returns null with no production manifest loaded, for any name/variant', () => {
    expect(resolvePropSprite('olive_tree', 0)).toBeNull();
    expect(resolvePropSprite('not_a_real_prop', 0)).toBeNull();
  });
});

describe('resolveSilhouette', () => {
  it('gives every named building kind a distinguishing feature, and an unknown kind none', () => {
    expect(resolveSilhouette('oracle')).toBe('columns');
    expect(resolveSilhouette('forge')).toBe('chimney');
    expect(resolveSilhouette('unknown-kind')).toBe('none');
  });
});
