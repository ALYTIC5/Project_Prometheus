import { describe, expect, it } from 'vitest';
import { PALETTE, snapToPalette } from './palette';

describe('PALETTE', () => {
  it('has exactly 32 entries (8 families x 4 values)', () => {
    expect(Object.keys(PALETTE)).toHaveLength(32);
  });

  it('every entry is a valid 24-bit colour', () => {
    for (const color of Object.values(PALETTE)) {
      expect(color).toBeGreaterThanOrEqual(0);
      expect(color).toBeLessThanOrEqual(0xffffff);
      expect(Number.isInteger(color)).toBe(true);
    }
  });
});

describe('snapToPalette', () => {
  it('is idempotent on an exact palette member', () => {
    const sample = PALETTE['blue.light'];
    expect(snapToPalette(sample)).toBe(sample);
  });

  it('maps the real building colours to a sane family', () => {
    // From prometheus/world/construction.py's BUILDING_COLORS.
    expect(snapToPalette(0x4a90d9)).toBe(PALETTE['blue.light']); // library
    expect(snapToPalette(0xe67e22)).toBe(PALETTE['orange.light']); // forge
    expect(snapToPalette(0x8e44ad)).toBe(PALETTE['purple.light']); // oracle
    expect(snapToPalette(0xe74c3c)).toBe(PALETTE['red.light']); // watchtower
  });
});
