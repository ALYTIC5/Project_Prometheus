import { describe, expect, it } from 'vitest';
import { directionIndexFor } from './direction';

describe('directionIndexFor', () => {
  it('maps each of the 8 exact compass headings to ROTATION_INDEX order', () => {
    expect(directionIndexFor(0, 1)).toBe(0); // south
    expect(directionIndexFor(1, 1)).toBe(1); // south-east
    expect(directionIndexFor(1, 0)).toBe(2); // east
    expect(directionIndexFor(1, -1)).toBe(3); // north-east
    expect(directionIndexFor(0, -1)).toBe(4); // north
    expect(directionIndexFor(-1, -1)).toBe(5); // north-west
    expect(directionIndexFor(-1, 0)).toBe(6); // west
    expect(directionIndexFor(-1, 1)).toBe(7); // south-west
  });

  it('is deterministic for the zero vector', () => {
    expect(directionIndexFor(0, 0)).toBe(directionIndexFor(0, 0));
  });

  it('always returns an index in [0, 7]', () => {
    for (let deg = 0; deg < 360; deg += 5) {
      const rad = (deg * Math.PI) / 180;
      const idx = directionIndexFor(Math.cos(rad), Math.sin(rad));
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThanOrEqual(7);
      expect(Number.isInteger(idx)).toBe(true);
    }
  });
});
