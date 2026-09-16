/**
 * Isometric grid<->screen conversion at the 2:1 pixel ratio (the
 * pixel-art convention — not true 30-degree isometric, see PROMPTS.md).
 *
 * Depth sorting is implemented here (depthOf); the algorithm is ported
 * from github.com/0xheycat/isometric-game-skills (attribution in
 * docs/DEPENDENCIES.md). A* pathfinding and autotiling from that toolkit
 * remain deferred — there is still no backend concept of an agent moving
 * between two real locations (see docs/DEPENDENCIES.md).
 */

export const TILE_WIDTH = 64;
export const TILE_HEIGHT = 32;
export const ELEVATION_UNIT = 16;

export interface ScreenPoint {
  x: number;
  y: number;
}

/** Painter's-algorithm sort layers, low to high (later layers draw on top
 * of earlier ones when depth values are otherwise equal). */
export enum Layer {
  GROUND = 0,
  ROAD = 1,
  PROP = 2,
  BUILDING = 3,
  AGENT = 4,
  EFFECT = 5,
  LABEL = 6,
}

/** Grid coordinates (building location units) -> screen pixels.
 * `elevation` raises the point (in storeys) without moving it on the
 * ground plane — used for building height and camera-independent lift. */
export function gridToScreen(gridX: number, gridY: number, elevation = 0): ScreenPoint {
  return {
    x: (gridX - gridY) * (TILE_WIDTH / 2),
    y: (gridX + gridY) * (TILE_HEIGHT / 2) - elevation * ELEVATION_UNIT,
  };
}

/** Screen pixels -> grid coordinates (inverse of gridToScreen at elevation 0). */
export function screenToGrid(screenX: number, screenY: number): ScreenPoint {
  const gridX = screenX / TILE_WIDTH + screenY / TILE_HEIGHT;
  const gridY = screenY / TILE_HEIGHT - screenX / TILE_WIDTH;
  return { x: gridX, y: gridY };
}

/** Painter's-algorithm sort key. Keyed on the footprint's FAR corner (not
 * its origin) so a multi-tile building sorts correctly against smaller
 * neighbours whose origin is numerically greater but whose footprint
 * doesn't reach as far. `layer` breaks ties between coincident footprints
 * on different visual layers (e.g. a ground tile under a building). */
export function depthOf(
  gridX: number,
  gridY: number,
  footprintWidth: number,
  footprintHeight: number,
  layer: Layer,
): number {
  const farCorner = gridX + footprintWidth - 1 + (gridY + footprintHeight - 1);
  return farCorner * 1000 + layer;
}
