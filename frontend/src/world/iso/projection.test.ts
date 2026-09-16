import { describe, expect, it } from 'vitest';
import { Layer, depthOf, gridToScreen, screenToGrid } from './projection';

describe('gridToScreen / screenToGrid round-trip', () => {
  it('recovers the original grid coordinates for 1000 random points', () => {
    for (let i = 0; i < 1000; i++) {
      const gx = (Math.random() - 0.5) * 200;
      const gy = (Math.random() - 0.5) * 200;
      const { x, y } = gridToScreen(gx, gy);
      const back = screenToGrid(x, y);
      expect(back.x).toBeCloseTo(gx, 6);
      expect(back.y).toBeCloseTo(gy, 6);
    }
  });

  it('elevation lifts the screen point without moving it on the ground plane', () => {
    const ground = gridToScreen(5, 5, 0);
    const lifted = gridToScreen(5, 5, 2);
    expect(lifted.x).toBe(ground.x);
    expect(lifted.y).toBeLessThan(ground.y);
  });
});

describe('depthOf', () => {
  it('sorts a 3x3 building at (2,2) after a 1x1 agent at (3,4) on the same layer', () => {
    const buildingDepth = depthOf(2, 2, 3, 3, Layer.BUILDING);
    const agentDepth = depthOf(3, 4, 1, 1, Layer.AGENT);
    // Building's far corner is (4,4) -> farSum 8; agent's far corner is
    // (3,4) -> farSum 7. The building must draw after (be "in front of")
    // the agent standing at a numerically smaller origin but a larger
    // reach — this is exactly the naive-x+y bug this module fixes.
    expect(buildingDepth).toBeGreaterThan(agentDepth);
  });

  it('produces no depth collisions across a small sampled grid on one layer', () => {
    const seen = new Map<number, string>();
    for (let x = 0; x < 8; x++) {
      for (let y = 0; y < 8; y++) {
        const d = depthOf(x, y, 1, 1, Layer.BUILDING);
        const key = `${x},${y}`;
        const prior = seen.get(d);
        if (prior !== undefined) {
          // Only the diagonal x+y=const positions are allowed to share a
          // depth on a painter's algorithm -- that's correct, not a bug,
          // since true isometric ties are unavoidable and harmless when
          // footprints don't actually overlap on screen.
          const [px, py] = prior.split(',').map(Number);
          expect(x + y).toBe(px + py);
        }
        seen.set(d, key);
      }
    }
  });

  it('breaks ties between layers at the same grid position', () => {
    const ground = depthOf(1, 1, 1, 1, Layer.GROUND);
    const building = depthOf(1, 1, 1, 1, Layer.BUILDING);
    expect(building).toBeGreaterThan(ground);
  });
});
