import * as PIXI from 'pixi.js';
import { gridToScreen } from '../iso/projection';
import type { Building, BuildingLocation } from '../types';

/** Screen->grid picking must go through the camera's actual inverse
 * transform, not a hand-rolled one -- Pixi's Container.toLocal() already
 * does exactly that (pan + zoom + any future rotation), so pickBuilding
 * asks the world container to invert the point rather than re-deriving
 * camera math here. This replaces the old bounding-box-on-sprites hit
 * test (the cause of wrong-building selections) with a real footprint
 * lookup against each building's actual grid rectangle. */
export function pickBuilding(
  globalPoint: PIXI.PointData,
  worldContainer: PIXI.Container,
  buildings: Building[],
): string | null {
  const local = worldContainer.toLocal(globalPoint);
  const gridX = local.x / 64 + local.y / 32;
  const gridY = local.y / 32 - local.x / 64;
  for (const building of buildings) {
    const { x, y, width, height } = building.location;
    if (gridX >= x && gridX < x + width && gridY >= y && gridY < y + height) {
      return building.id;
    }
  }
  return null;
}

function footprintCorners(loc: BuildingLocation): PIXI.PointData[] {
  return [
    gridToScreen(loc.x, loc.y),
    gridToScreen(loc.x + loc.width, loc.y),
    gridToScreen(loc.x + loc.width, loc.y + loc.height),
    gridToScreen(loc.x, loc.y + loc.height),
  ];
}

/** Warm-white isometric footprint outline for hover -- replaces the old
 * axis-aligned red rectangle. */
export function drawHoverOutline(loc: BuildingLocation): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const corners = footprintCorners(loc);
  g.poly(corners.flatMap((p) => [p.x, p.y])).stroke({ color: 0xfff4d6, width: 2, alpha: 0.85 });
  return g;
}

/** Pulsing isometric footprint outline plus a vertical light shaft, for
 * the selected building. `phaseMs` drives the pulse -- caller owns time. */
export function drawSelectionOutline(loc: BuildingLocation, phaseMs: number): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const corners = footprintCorners(loc);
  const pulse = 0.5 + 0.5 * Math.sin(phaseMs / 300);
  g.poly(corners.flatMap((p) => [p.x, p.y])).stroke({
    color: 0xffe27a,
    width: 2 + pulse,
    alpha: 0.6 + 0.4 * pulse,
  });

  const center = gridToScreen(loc.x + loc.width / 2, loc.y + loc.height / 2);
  const shaftHeight = 140;
  g.poly([
    center.x - 6,
    center.y,
    center.x + 6,
    center.y,
    center.x + 2,
    center.y - shaftHeight,
    center.x - 2,
    center.y - shaftHeight,
  ]).fill({ color: 0xffe27a, alpha: 0.12 + 0.08 * pulse });

  return g;
}
