import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import { PALETTE } from '../sprites/palette';
import { hashString } from '../sprites/registry';
import { GRID_SIZE, WATER_MAX_X, PLAZA_RADIUS, computeRoadTiles, isInsideAnyFootprint } from './ground';
import type { Building } from '../../types';

// Tree line thickness at the island edge, and how close to the Underworld
// building's centre counts as "the Underworld quarter" for the bare/dead
// variant -- both hand-tuned to this repo's real 26x26 grid
// (prometheus/world/construction.py), not invented constants.
const EDGE_MARGIN = 2;
const UNDERWORLD_RADIUS = 5;

type Kind = 'tree' | 'bush' | 'tuft';

function isNearEdge(gx: number, gy: number): boolean {
  return gx < EDGE_MARGIN || gx >= GRID_SIZE - EDGE_MARGIN || gy < EDGE_MARGIN || gy >= GRID_SIZE - EDGE_MARGIN;
}

function underworldCentre(buildings: Building[]): { x: number; y: number } | null {
  const underworld = buildings.find((b) => b.kind === 'underworld');
  if (!underworld) return null;
  return {
    x: underworld.location.x + underworld.location.width / 2,
    y: underworld.location.y + underworld.location.height / 2,
  };
}

function isUnderworldZone(gx: number, gy: number, centre: { x: number; y: number } | null): boolean {
  if (!centre) return false;
  return Math.hypot(gx - centre.x, gy - centre.y) <= UNDERWORLD_RADIUS;
}

/** Deterministic hash of (gx, gy) -> whether/what grows here, and which of
 * a small set of look variants -- same source as ground.ts's terrainHash.
 * No runtime randomness anywhere: the world stays a pure function of state. */
function vegetationAt(gx: number, gy: number, dead: boolean): { kind: Kind; variant: number } | null {
  const h = hashString(`veg:${gx},${gy}`);
  const nearEdge = isNearEdge(gx, gy);

  if (nearEdge) {
    // Dense tree line around the perimeter -- most edge tiles get a tree.
    if (h % 5 !== 0) return { kind: 'tree', variant: h % 3 };
    return null;
  }
  // Sparser interior scatter: mostly empty ground (negative space), with
  // occasional bushes/tufts, and trees clustering as district separators.
  const roll = h % 12;
  if (roll === 0) return { kind: 'tree', variant: h % 3 };
  if (roll === 1 || roll === 2) return { kind: 'bush', variant: h % 2 };
  if (roll === 3) return { kind: 'tuft', variant: 0 };
  if (dead && roll === 4) return { kind: 'tree', variant: h % 3 }; // extra bare trees in the Underworld
  return null;
}

function drawTree(variant: number, dead: boolean): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const trunkColor = dead ? PALETTE['slate.dark'] : PALETTE['orange.dark'];
  const canopyColor = dead ? PALETTE['slate.mid'] : [PALETTE['green.dark'], PALETTE['green.mid'], PALETTE['green.light']][variant];
  const trunkHeight = 6 + variant;
  g.rect(-1, -trunkHeight, 2, trunkHeight).fill({ color: trunkColor });
  if (dead) {
    // Bare silhouette: a few bark-coloured branches, no canopy fill --
    // same silhouette language as a live tree, inverted meaning.
    g.moveTo(0, -trunkHeight).lineTo(-3, -trunkHeight - 4).stroke({ color: canopyColor, width: 1 });
    g.moveTo(0, -trunkHeight).lineTo(3, -trunkHeight - 3).stroke({ color: canopyColor, width: 1 });
    g.moveTo(0, -trunkHeight + 2).lineTo(-2, -trunkHeight - 2).stroke({ color: canopyColor, width: 1 });
  } else {
    g.circle(0, -trunkHeight - 3, 4 + variant).fill({ color: canopyColor });
  }
  return g;
}

function drawBush(variant: number): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const color = variant === 0 ? PALETTE['green.mid'] : PALETTE['green.dark'];
  g.circle(-2, -2, 2.5).fill({ color });
  g.circle(2, -1.5, 2.5).fill({ color });
  g.circle(0, -3, 2.5).fill({ color });
  return g;
}

function drawTuft(): PIXI.Graphics {
  const g = new PIXI.Graphics();
  g.moveTo(-2, 0).lineTo(-1, -4).stroke({ color: PALETTE['green.light'], width: 1 });
  g.moveTo(0, 0).lineTo(0, -5).stroke({ color: PALETTE['green.highlight'], width: 1 });
  g.moveTo(2, 0).lineTo(1, -4).stroke({ color: PALETTE['green.light'], width: 1 });
  return g;
}

/** Static procedural vegetation -- no PixelLab tree/prop art exists yet and
 * the MCP server isn't installed to generate any, so these are PixiJS
 * Graphics drawn from PALETTE, same as builders.ts's procedural fallback.
 * Deterministic placement per tile; recomputed fresh on every redraw. */
export function createVegetation(buildings: Building[]): PIXI.Container[] {
  const roads = computeRoadTiles(buildings);
  const monument = buildings.find((b) => b.kind === 'monument');
  const underworldCenter = underworldCentre(buildings);
  const roots: PIXI.Container[] = [];

  for (let gx = 0; gx < GRID_SIZE; gx++) {
    for (let gy = 0; gy < GRID_SIZE; gy++) {
      if (gx < WATER_MAX_X) continue;
      if (isInsideAnyFootprint(gx, gy, buildings)) continue;
      if (roads.has(`${gx},${gy}`)) continue;
      const isPlaza =
        !!monument && Math.abs(gx - monument.location.x) <= PLAZA_RADIUS && Math.abs(gy - monument.location.y) <= PLAZA_RADIUS;
      if (isPlaza) continue;

      const dead = isUnderworldZone(gx, gy, underworldCenter);
      const plant = vegetationAt(gx, gy, dead);
      if (!plant) continue;

      const { x, y } = gridToScreen(gx, gy);
      const root = new PIXI.Container();
      root.addChild(
        plant.kind === 'tree' ? drawTree(plant.variant, dead) : plant.kind === 'bush' ? drawBush(plant.variant) : drawTuft(),
      );
      root.x = x;
      root.y = y;
      root.zIndex = depthOf(gx, gy, 1, 1, Layer.PROP);
      roots.push(root);
    }
  }

  return roots;
}
