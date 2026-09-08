import { describe, expect, it } from 'vitest';
import { classifyFootprint, resolveSilhouette, resolveSprite } from './registry';

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

describe('resolveSilhouette', () => {
  it('gives every named building kind a distinguishing feature, and an unknown kind none', () => {
    expect(resolveSilhouette('oracle')).toBe('columns');
    expect(resolveSilhouette('forge')).toBe('chimney');
    expect(resolveSilhouette('unknown-kind')).toBe('none');
  });
});
