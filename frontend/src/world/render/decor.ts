import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import { hashString } from '../sprites/registry';
import {
  GRID_SIZE,
  WATER_MAX_X,
  PLAZA_RADIUS,
  computeRoadTiles,
  isInsideAnyFootprint,
} from './ground';
import { atlasSprite, isUnderworldZone, underworldCentre, vegetationAt } from './vegetation';
import type { Building } from '../../types';

/** Standalone decor props with real PixelLab art but no procedural
 * equivalent (see tools/art/build_r2_manifest.py) -- each has exactly one
 * atlas variant (index 0). Unlike vegetation, these render NOTHING when no
 * real art is loaded (SPRITE_SET=placeholder, or the atlas hasn't loaded
 * yet): inventing a crude placeholder shape for a herm statue or a
 * brazier is a real art/design decision nobody has made, not something to
 * improvise here (contrast vegetation.ts's tree/bush, which already had an
 * established procedural look before any real art existed). */
export const DECOR_NAMES = [
  'amphora_pair',
  'column_fragment',
  'tripod_brazier',
  'stone_bench',
  'herm_statue',
] as const;

// Sparse and occasional by design -- 5 distinct hand-placed-feeling objects
// scattered across a 26x26 grid should read as deliberate civic furnishing,
// not wallpaper. Compare vegetation's much denser roll (~1 in 4-12 tiles).
const DECOR_DENSITY = 40;

/** Deterministic (gx, gy) -> decor name, or null. Pure and independently
 * testable, same split as vegetation.ts's vegetationAt/drawTree. Never
 * fires on a tile vegetation already used (`occupied`), in the Underworld
 * zone (civic furnishing doesn't belong in a dead district), or anywhere
 * vegetationAt's own exclusions already forbid (footprints/roads/plaza/
 * water -- enforced by the caller's loop, same as vegetation.ts). */
export function decorAt(gx: number, gy: number, occupied: boolean): (typeof DECOR_NAMES)[number] | null {
  if (occupied) return null;
  const h = hashString(`decor:${gx},${gy}`);
  if (h % DECOR_DENSITY !== 0) return null;
  return DECOR_NAMES[hashString(`decor-which:${gx},${gy}`) % DECOR_NAMES.length];
}

/** Static decor scatter -- amphorae, a fallen column, a brazier, a bench, a
 * herm. Deterministic placement per tile, recomputed fresh on every redraw
 * (W1: pure function of state, no persisted randomness). No-op entirely
 * when no real art is loaded, by design (see DECOR_NAMES's docstring). */
export function createDecor(buildings: Building[]): PIXI.Container[] {
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
      if (isUnderworldZone(gx, gy, underworldCenter)) continue;

      const occupied = vegetationAt(gx, gy, false) !== null;
      const name = decorAt(gx, gy, occupied);
      if (!name) continue;

      const sprite = atlasSprite(name, 0);
      if (!sprite) continue; // placeholder mode / atlas not loaded -- render nothing, not a guess

      const { x, y } = gridToScreen(gx, gy);
      sprite.x = x;
      sprite.y = y;
      sprite.zIndex = depthOf(gx, gy, 1, 1, Layer.PROP);
      roots.push(sprite);
    }
  }

  return roots;
}
