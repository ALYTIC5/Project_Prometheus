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

  it('maps the real building colours to the correct family (shade may drift when palette.json changes)', () => {
    // From prometheus/world/construction.py's BUILDING_COLORS. Asserts the
    // FAMILY (hue) stays correct -- the specific nearest SHADE is a function
    // of palette.json's exact values and legitimately shifts when the tonal
    // range changes (see the tonal-fix session that brightened palette.json).
    for (const [name, hex, family] of [
      ['library', 0x4a90d9, 'blue'],
      ['forge', 0xe67e22, 'orange'],
      ['oracle', 0x8e44ad, 'purple'],
      ['watchtower', 0xe74c3c, 'red'],
    ] as const) {
      const snapped = snapToPalette(hex);
      const matchedKey = Object.entries(PALETTE).find(([, v]) => v === snapped)?.[0];
      expect(matchedKey?.startsWith(`${family}.`), `${name}: expected a ${family}.* shade, got ${matchedKey}`).toBe(true);
    }
  });
});
