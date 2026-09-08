import * as PIXI from 'pixi.js';
import { gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';

/** Matches the backend's hand-authored layout grid
 * (prometheus/world/construction.py). */
export const GRID_SIZE = 26;
/** Columns x<2 are reserved as water, beyond the Harbour's edge placement
 * (prometheus/world/construction.py: harbour sits at x=2). */
export const WATER_MAX_X = 2;

const TILE_COLOR_A = 0x14241a;
const TILE_COLOR_B = 0x18291f;
const WATER_COLOR = 0x0f2a3a;

/** Draws the full tile grid as individual diamonds (not one flat rect), so
 * the isometric grid is legible. This container is always the backmost
 * layer by insertion order (see components/WorldView.tsx) -- it must NOT
 * carry a zIndex of its own, and must not be a sibling inside a
 * sortableChildren container with buildings/agents: depthOf() produces
 * per-tile/per-object sort keys, and applying that formula to this single
 * aggregate container (as an earlier version of this file did) gave it a
 * zIndex larger than any individual building's, sorting the entire ground
 * plane on top of every building. */
export function drawGround(): PIXI.Container {
  const container = new PIXI.Container();

  for (let gx = 0; gx < GRID_SIZE; gx++) {
    for (let gy = 0; gy < GRID_SIZE; gy++) {
      const { x, y } = gridToScreen(gx, gy);
      const isWater = gx < WATER_MAX_X;
      const color = isWater ? WATER_COLOR : (gx + gy) % 2 === 0 ? TILE_COLOR_A : TILE_COLOR_B;
      const halfW = TILE_WIDTH / 2;
      const halfH = TILE_HEIGHT / 2;
      const tile = new PIXI.Graphics();
      tile.poly([0, -halfH, halfW, 0, 0, halfH, -halfW, 0]).fill({ color });
      tile.x = x;
      tile.y = y;
      container.addChild(tile);
    }
  }

  return container;
}
