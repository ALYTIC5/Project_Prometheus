import { describe, expect, it } from 'vitest';
import { DECOR_NAMES, decorAt } from './decor';

describe('decorAt', () => {
  it('never fires on an occupied (vegetation-claimed) tile', () => {
    for (let gx = 0; gx < 26; gx++) {
      for (let gy = 0; gy < 26; gy++) {
        expect(decorAt(gx, gy, true)).toBeNull();
      }
    }
  });

  it('is deterministic -- same (gx, gy) always gives the same answer', () => {
    for (let gx = 0; gx < 26; gx++) {
      for (let gy = 0; gy < 26; gy++) {
        expect(decorAt(gx, gy, false)).toBe(decorAt(gx, gy, false));
      }
    }
  });

  it('only ever returns a name from DECOR_NAMES, or null', () => {
    for (let gx = 0; gx < 26; gx++) {
      for (let gy = 0; gy < 26; gy++) {
        const result = decorAt(gx, gy, false);
        if (result !== null) expect(DECOR_NAMES).toContain(result);
      }
    }
  });

  it('is sparse: fires on well under half the unoccupied tiles of a 26x26 grid', () => {
    let count = 0;
    for (let gx = 0; gx < 26; gx++) {
      for (let gy = 0; gy < 26; gy++) {
        if (decorAt(gx, gy, false) !== null) count++;
      }
    }
    expect(count).toBeGreaterThan(0); // not dead code
    expect(count).toBeLessThan((26 * 26) / 10);
  });
});
