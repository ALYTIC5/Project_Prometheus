import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import { getAtlasFrame } from '../sprites/atlasTextures';
import { directionIndexFor } from '../sprites/direction';
import { resolveCharacterSprite } from '../sprites/registry';
import type { Building } from '../types';

// prometheus/world/construction.py's BUILDING_LOCATIONS -- see builders.ts.
const MONUMENT_GRID = { x: 13, y: 13 };

/** Building kind -> the one god whose identity IS that building, not its
 * activity, so there is no construction_phase threshold to invent -- the
 * god renders whenever its building does.
 *
 * Only 3 of the 12 imported gods have a real building to stand at. The
 * other 9 (the 8 strategy-family gods + god_evolution) are per strategy
 * FAMILY, and `districts[]` is always empty -- no strategy_families table
 * exists yet (docs/WORLD_MAPPING.md; prometheus/world/projection.py hardcodes
 * this with a comment that a fabricated district would be the world lying).
 * Those 9 are imported and atlased (visible on the /sprites roster route)
 * but deliberately never spawned here. */
const GOD_BY_BUILDING_KIND: Record<string, string> = {
  archive: 'archive_keeper',
  oracle: 'oracle_validation',
  vault: 'risk_guardian',
};

/** Static idle gods standing at their real building -- same anchor/zIndex
 * contract as render/builders.ts's figures, but with no update() loop:
 * there is no animation to advance (idle-only art, no per-frame state). */
export function createGods(buildings: Building[]): PIXI.Container[] {
  const monumentScreen = gridToScreen(MONUMENT_GRID.x, MONUMENT_GRID.y);
  const roots: PIXI.Container[] = [];

  for (const building of buildings) {
    const godName = GOD_BY_BUILDING_KIND[building.kind];
    if (!godName) continue;

    // Opposite corner from builders.ts's *0.75 anchor so a god and a
    // construction-phase agent figure never occupy the same building tile.
    const edgeX = building.location.x + building.location.width * 0.25;
    const edgeY = building.location.y + building.location.height * 0.25;
    const { x, y } = gridToScreen(edgeX, edgeY);
    const rotation = directionIndexFor(monumentScreen.x - x, monumentScreen.y - y);
    const spec = resolveCharacterSprite(godName, 'idle', rotation);
    const texture = spec?.atlas && spec.frame && spec.anchor ? getAtlasFrame(spec) : null;
    if (!texture || !spec?.frame || !spec.anchor) continue; // placeholder mode or atlas not loaded -- no art, no figure

    const sprite = new PIXI.Sprite(texture);
    sprite.anchor.set(spec.anchor.x / spec.frame.width, spec.anchor.y / spec.frame.height);
    const root = new PIXI.Container();
    root.addChild(sprite);
    root.x = x;
    root.y = y;
    root.zIndex = depthOf(edgeX, edgeY, 1, 1, Layer.AGENT);
    roots.push(root);
  }

  return roots;
}
