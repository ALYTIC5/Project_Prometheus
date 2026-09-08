import * as PIXI from 'pixi.js';
import { gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';
import { hashString } from '../sprites/registry';
import { PALETTE } from '../sprites/palette';
import type { Building } from '../types';

/** Matches the backend's hand-authored layout grid
 * (prometheus/world/construction.py). */
export const GRID_SIZE = 26;
/** Columns x<2 are reserved as water, beyond the Harbour's edge placement
 * (prometheus/world/construction.py: harbour sits at x=2). */
export const WATER_MAX_X = 2;
/** Mirrors prometheus/world/construction.py's MONUMENT_CLEAR_RADIUS -- a
 * rendering convenience, not a shared import (different languages/
 * processes), verified visually rather than by a shared constant. */
export const PLAZA_RADIUS = 2;

const TERRAIN_VARIANTS = [PALETTE['green.dark'], PALETTE['green.mid'], PALETTE['slate.dark'], PALETTE['stone.dark']];
const WATER_COLOR = PALETTE['blue.dark'];
const PLAZA_COLOR = PALETTE['stone.light'];
const ROAD_BASE = PALETTE['stone.mid'];
const ROAD_LINE = PALETTE['stone.highlight'];

function terrainHash(gx: number, gy: number): number {
  return hashString(`${gx},${gy}`) % TERRAIN_VARIANTS.length;
}

function footprintOf(b: Building) {
  return { x: b.location.x, y: b.location.y, w: b.location.width, h: b.location.height };
}

function isInsideAnyFootprint(gx: number, gy: number, buildings: Building[]): boolean {
  return buildings.some((b) => {
    const f = footprintOf(b);
    return gx >= f.x && gx < f.x + f.w && gy >= f.y && gy < f.y + f.h;
  });
}

/** Straight-corridor road network: a main N-S/E-W avenue through the
 * Monument's real plaza position, plus one straight connector per
 * building toward whichever avenue axis is closer. Skips any cell that
 * falls inside a building's real footprint (roads run in the 1-tile gaps
 * the layout already guarantees, per tests/test_building_layout.py) --
 * this is intentionally simpler than a general autotiling ruleset (see
 * docs/DEPENDENCIES.md): one fixed hand-authored layout, not a terrain
 * editor. */
function computeRoadTiles(buildings: Building[]): Set<string> {
  const roads = new Set<string>();
  const monument = buildings.find((b) => b.kind === 'monument');
  if (!monument) return roads;
  const avenueX = Math.round(monument.location.x);
  const avenueY = Math.round(monument.location.y);

  for (let gx = 0; gx < GRID_SIZE; gx++) roads.add(`${gx},${avenueY}`);
  for (let gy = 0; gy < GRID_SIZE; gy++) roads.add(`${avenueX},${gy}`);

  for (const b of buildings) {
    const f = footprintOf(b);
    const cx = Math.round(f.x + f.w / 2);
    const cy = Math.round(f.y + f.h / 2);
    const distToRow = Math.abs(cy - avenueY);
    const distToCol = Math.abs(cx - avenueX);
    if (distToRow <= distToCol) {
      const step = cy < avenueY ? 1 : -1;
      for (let gy = cy; gy !== avenueY; gy += step) roads.add(`${cx},${gy}`);
    } else {
      const step = cx < avenueX ? 1 : -1;
      for (let gx = cx; gx !== avenueX; gx += step) roads.add(`${gx},${cy}`);
    }
  }

  for (const key of Array.from(roads)) {
    const [gx, gy] = key.split(',').map(Number);
    if (isInsideAnyFootprint(gx, gy, buildings)) roads.delete(key);
  }
  return roads;
}

function drawRoadTile(gx: number, gy: number, roads: Set<string>): PIXI.Graphics {
  const north = roads.has(`${gx},${gy - 1}`);
  const south = roads.has(`${gx},${gy + 1}`);
  const east = roads.has(`${gx + 1},${gy}`);
  const west = roads.has(`${gx - 1},${gy}`);
  const halfW = TILE_WIDTH / 2;
  const halfH = TILE_HEIGHT / 2;

  const tile = new PIXI.Graphics();
  tile.poly([0, -halfH, halfW, 0, 0, halfH, -halfW, 0]).fill({ color: ROAD_BASE });

  // Autotile "variant" is really just which directions the centre line
  // reaches -- straight, corner, T, or cross -- picked from the 4
  // neighbour flags rather than a distinct texture per bitmask.
  if (north) tile.moveTo(0, 0).lineTo(0, -halfH).stroke({ color: ROAD_LINE, width: 2 });
  if (south) tile.moveTo(0, 0).lineTo(0, halfH).stroke({ color: ROAD_LINE, width: 2 });
  if (east) tile.moveTo(0, 0).lineTo(halfW, 0).stroke({ color: ROAD_LINE, width: 2 });
  if (west) tile.moveTo(0, 0).lineTo(-halfW, 0).stroke({ color: ROAD_LINE, width: 2 });

  return tile;
}

/** Draws the full tile grid as individual diamonds (not one flat rect), so
 * the isometric grid is legible. This container is always the backmost
 * layer by insertion order (see components/WorldView.tsx) -- it must NOT
 * carry a zIndex of its own, and must not be a sibling inside a
 * sortableChildren container with buildings/agents: depthOf() produces
 * per-tile/per-object sort keys, and applying that formula to this single
 * aggregate container (as an earlier version of this file did) gave it a
 * zIndex larger than any individual building's, sorting the entire ground
 * plane on top of every building. */
export function drawGround(buildings: Building[]): PIXI.Container {
  const container = new PIXI.Container();
  const monument = buildings.find((b) => b.kind === 'monument');
  const roads = computeRoadTiles(buildings);

  for (let gx = 0; gx < GRID_SIZE; gx++) {
    for (let gy = 0; gy < GRID_SIZE; gy++) {
      const { x, y } = gridToScreen(gx, gy);
      const isWater = gx < WATER_MAX_X;
      const isPlaza =
        !!monument &&
        Math.abs(gx - monument.location.x) <= PLAZA_RADIUS &&
        Math.abs(gy - monument.location.y) <= PLAZA_RADIUS;
      const isRoad = roads.has(`${gx},${gy}`);

      let tile: PIXI.Graphics;
      if (isRoad && !isWater) {
        tile = drawRoadTile(gx, gy, roads);
      } else {
        const halfW = TILE_WIDTH / 2;
        const halfH = TILE_HEIGHT / 2;
        const color = isWater ? WATER_COLOR : isPlaza ? PLAZA_COLOR : TERRAIN_VARIANTS[terrainHash(gx, gy)];
        tile = new PIXI.Graphics();
        tile.poly([0, -halfH, halfW, 0, 0, halfH, -halfW, 0]).fill({ color });
      }
      tile.x = x;
      tile.y = y;
      container.addChild(tile);
    }
  }

  return container;
}
