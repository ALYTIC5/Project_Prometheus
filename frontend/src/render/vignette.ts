import * as PIXI from 'pixi.js';

/** Subtle screen-space vignette (darker corners) -- added directly to
 * app.stage, not `world`, so it stays fixed relative to the viewport
 * rather than panning/zooming with the camera. This is one of the few
 * places this renderer uses alpha on purpose: it's an atmosphere effect,
 * not a structural fill. */
export function drawVignette(width: number, height: number): PIXI.Graphics {
  const g = new PIXI.Graphics();
  const rings: [number, number][] = [
    [1.15, 0.28],
    [0.95, 0.16],
    [0.75, 0.08],
  ];
  const cx = width / 2;
  const cy = height / 2;
  const maxR = Math.hypot(cx, cy);
  for (const [factor, alpha] of rings) {
    g.circle(cx, cy, maxR * factor).fill({ color: 0x000000, alpha });
  }
  // Punch the centre back to fully clear so only the corners/edges darken.
  g.circle(cx, cy, maxR * 0.55).cut();
  return g;
}
