import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';
import { STOREY_PIXEL_HEIGHT } from '../sprites/registry';

const STONE_COLOR = 0x9a9488;
const STONE_DARK = 0x6f6a60;
// A pre-mixed solid (not an alpha blend over STONE_DARK) for the shaft's
// shadow edge -- Part 1's rule is alpha=1.0 on every structural fill.
const SHAFT_SHADOW = 0x433f38;
const BASE_HEIGHT = 60;
/** Tallest structure in the city -- 10 storeys, the same unit every other
 * building's height comes from (render/building.ts), so the Monument
 * scales consistently if that constant is ever retuned. */
const MAX_HEIGHT = 10 * STOREY_PIXEL_HEIGHT;
const MIN_HEIGHT = 30;
/** Ease the monument's height toward the real benchmark equity over ~2s,
 * rather than snapping -- it is the city's one deliberately alive figure. */
const EASE_PER_MS = 1 / 2000;

export interface MonumentHandle {
  container: PIXI.Container;
  /** Call every frame with the real current benchmark equity and the
   * frame's delta time in ms. Eases toward the target, never snaps. */
  update: (targetEquity: number, deltaMs: number) => void;
}

function heightForEquity(equity: number): number {
  const ratio = Math.max(0.2, equity / 1000);
  return Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, BASE_HEIGHT * ratio));
}

/** The Monument is the one deliberate exception to "every building is the
 * same shape" (PROMPTS.md is explicit): a stepped stone obelisk, alone on
 * a plaza, in an older/cooler palette than every other structure, with its
 * height driven by the real (currently flat, since benchmark_equity has no
 * rows yet) buy-and-hold benchmark value -- never occluded, because the
 * backend layout gives it a guaranteed clear radius. */
export function createMonument(gridX: number, gridY: number, initialEquity: number): MonumentHandle {
  const container = new PIXI.Container();
  const anchor = gridToScreen(gridX + 0.5, gridY + 0.5);
  container.x = anchor.x;
  container.y = anchor.y;
  container.zIndex = depthOf(gridX, gridY, 1, 1, Layer.BUILDING);
  container.eventMode = 'static';
  container.cursor = 'pointer';
  (container as PIXI.Container & { __buildingId: string }).__buildingId = 'monument';

  const halfW = TILE_WIDTH * 0.35;
  const halfH = TILE_HEIGHT * 0.6;

  const graphics = new PIXI.Graphics();
  const plaque = new PIXI.Text({
    text: `€${Math.round(initialEquity)}`,
    style: { fill: 0xf5e6c8, fontSize: 10, fontFamily: 'monospace' },
  });
  plaque.anchor.set(0.5, 1);
  container.addChild(graphics);
  container.addChild(plaque);

  // Ground-glow -- concentric low-alpha rings so the eye lands here first.
  // This (and the spotlight cones below) is the one place outside weather/
  // selection/damage-smoke this renderer uses alpha: it's a genuine light
  // effect, not structural fill.
  const glow = new PIXI.Graphics();
  for (const [radius, alpha] of [
    [halfW * 3.2, 0.05],
    [halfW * 2.2, 0.09],
    [halfW * 1.3, 0.14],
  ] as const) {
    glow.ellipse(0, 0, radius, radius * 0.5).fill({ color: 0xffe8b0, alpha });
  }
  container.addChildAt(glow, 0);

  // Ground-level spotlights -- upward translucent light cones.
  const spotlights = new PIXI.Graphics();
  for (const angle of [Math.PI * 0.2, Math.PI * 0.8, Math.PI * 1.5]) {
    const bx = Math.cos(angle) * halfW * 1.8;
    const by = Math.sin(angle) * halfH * 1.8;
    spotlights
      .poly([bx - 4, by, bx + 4, by, bx + 14, by - 100, bx - 14, by - 100])
      .fill({ color: 0xfff2cc, alpha: 0.06 });
  }
  container.addChildAt(spotlights, 1);

  // Plaza dais -- a wide, flat stone platform under the obelisk itself.
  const dais = new PIXI.Graphics();
  dais.poly([0, -halfH * 1.6, halfW * 2.2, 0, 0, halfH * 1.6, -halfW * 2.2, 0]).fill({
    color: STONE_DARK,
  });
  container.addChildAt(dais, 2);

  let currentHeight = heightForEquity(initialEquity);

  function draw(height: number, equity: number): void {
    graphics.clear();
    // Stepped base -- three narrowing tiers, then the shaft.
    const tiers = 3;
    for (let t = 0; t < tiers; t++) {
      const tierH = height * 0.12;
      const y0 = -t * tierH;
      const w = halfW * (1.1 - t * 0.15);
      graphics
        .poly([-w, y0, w, y0, w * 0.85, y0 - tierH, -w * 0.85, y0 - tierH])
        .fill({ color: t % 2 === 0 ? STONE_COLOR : STONE_DARK });
    }
    const shaftTop = -height;
    const shaftBase = -tiers * height * 0.12;
    const shaftW = halfW * 0.5;
    graphics
      .poly([-shaftW, shaftBase, shaftW, shaftBase, shaftW * 0.6, shaftTop, -shaftW * 0.6, shaftTop])
      .fill({ color: STONE_COLOR });
    graphics
      .poly([shaftW, shaftBase, shaftW * 0.6, shaftTop, shaftW * 0.6 - 4, shaftTop, shaftW - 5, shaftBase])
      .fill({ color: SHAFT_SHADOW });

    // "€1,000" carved into the base plinth -- always readable, static.
    const base = new PIXI.Text({
      text: '€1,000',
      style: { fill: 0x3a352c, fontSize: 8, fontFamily: 'monospace' },
    });
    base.anchor.set(0.5, 0);
    base.y = -6;
    graphics.removeChildren();
    graphics.addChild(base);

    plaque.text = `€${Math.round(equity)}`;
    plaque.y = shaftTop - 6;
  }

  draw(currentHeight, initialEquity);

  function update(targetEquity: number, deltaMs: number): void {
    const targetHeight = heightForEquity(targetEquity);
    const step = EASE_PER_MS * deltaMs;
    currentHeight += (targetHeight - currentHeight) * Math.min(1, step);
    draw(currentHeight, targetEquity);
  }

  return { container, update };
}
