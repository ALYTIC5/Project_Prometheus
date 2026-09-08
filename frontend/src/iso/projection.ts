/**
 * Isometric grid<->screen conversion at the 2:1 pixel ratio (the
 * pixel-art convention — not true 30-degree isometric, see PROMPTS.md).
 *
 * This is only the projection formula. Depth sorting, A* pathfinding,
 * and autotiling (also called for in PROMPTS.md, ported from
 * github.com/0xheycat/isometric-game-skills) are deliberately NOT
 * implemented yet: nothing in the current WorldState needs them (no
 * agents exist until a real job queue does, in PROMPT 4), and building
 * one now would be premature — see docs/DEPENDENCIES.md for the
 * decision to defer.
 */

export const TILE_WIDTH = 64;
export const TILE_HEIGHT = 32;

export interface ScreenPoint {
  x: number;
  y: number;
}

/** Grid coordinates (building location units) -> screen pixels. */
export function gridToScreen(gridX: number, gridY: number): ScreenPoint {
  return {
    x: (gridX - gridY) * (TILE_WIDTH / 2),
    y: (gridX + gridY) * (TILE_HEIGHT / 2),
  };
}

/** Screen pixels -> grid coordinates (inverse of gridToScreen). */
export function screenToGrid(screenX: number, screenY: number): ScreenPoint {
  const gridX = screenX / TILE_WIDTH + screenY / TILE_HEIGHT;
  const gridY = screenY / TILE_HEIGHT - screenX / TILE_WIDTH;
  return { x: gridX, y: gridY };
}
