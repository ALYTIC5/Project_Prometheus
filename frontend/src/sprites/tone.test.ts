import { describe, expect, it } from 'vitest';
import paletteData from './palette.json';

// Rec.709 luminance, matching tools/art/compare_reference.py's definition
// exactly -- the two must agree on what "brightness" means.
function luminance(hex: string): number {
  const v = hex.replace('#', '');
  const r = parseInt(v.slice(0, 2), 16) / 255;
  const g = parseInt(v.slice(2, 4), 16) / 255;
  const b = parseInt(v.slice(4, 6), 16) / 255;
  return r * 0.2126 + g * 0.7152 + b * 0.0722;
}

const DEAD_BAND: [number, number] = [0.25, 0.35];

describe('palette.json tonal range', () => {
  it('has no entry in the dead band that reads as mud', () => {
    for (const [family, shades] of Object.entries(paletteData)) {
      for (const [shade, hex] of Object.entries(shades)) {
        const l = luminance(hex);
        expect(
          l <= DEAD_BAND[0] || l >= DEAD_BAND[1],
          `${family}.${shade} (${hex}) has luminance ${l.toFixed(3)}, inside the ${DEAD_BAND[0]}-${DEAD_BAND[1]} dead band`,
        ).toBe(true);
      }
    }
  });

  it('every family ramp is monotonically ascending dark -> highlight', () => {
    for (const [family, shades] of Object.entries(paletteData)) {
      const order = ['dark', 'mid', 'light', 'highlight'] as const;
      const lums = order.map((shade) => luminance((shades as Record<string, string>)[shade]));
      for (let i = 1; i < lums.length; i++) {
        expect(lums[i], `${family}: ${order[i - 1]} (${lums[i - 1].toFixed(3)}) should be darker than ${order[i]} (${lums[i].toFixed(3)})`).toBeGreaterThan(lums[i - 1]);
      }
    }
  });

  it('the darkest non-slate family floor is at least 0.35', () => {
    for (const [family, shades] of Object.entries(paletteData)) {
      if (family === 'slate') continue; // the one deliberately dark family
      const darkLum = luminance((shades as Record<string, string>).dark);
      expect(darkLum, `${family}.dark`).toBeGreaterThanOrEqual(0.35);
    }
  });

  it('the brightest tone in the palette is a real highlight (>=0.75)', () => {
    const allLums = Object.values(paletteData).flatMap((shades) =>
      Object.values(shades as Record<string, string>).map(luminance),
    );
    expect(Math.max(...allLums)).toBeGreaterThanOrEqual(0.75);
  });
});
