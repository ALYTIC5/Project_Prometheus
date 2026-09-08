import paletteData from './palette.json';

export type PaletteFamily = keyof typeof paletteData;
export type PaletteValue = 'dark' | 'mid' | 'light' | 'highlight';

function hexToNumber(hex: string): number {
  return parseInt(hex.replace('#', ''), 16);
}

/** Flat 32-entry colour table (8 hue families x 4 values), the one place
 * every renderer call site should get a colour from -- no inline hex
 * literals elsewhere (Part 2 of the world-renderer polish prompt). */
export const PALETTE: Record<string, number> = Object.fromEntries(
  Object.entries(paletteData).flatMap(([family, values]) =>
    Object.entries(values).map(([value, hex]) => [`${family}.${value}`, hexToNumber(hex)]),
  ),
);

const PALETTE_ENTRIES = Object.entries(PALETTE);

function toRgb(color: number): [number, number, number] {
  return [(color >> 16) & 0xff, (color >> 8) & 0xff, color & 0xff];
}

/** Quantises any colour (e.g. a building's raw API hex) to the nearest
 * colour actually in the palette, by RGB distance -- so procedural fills
 * and (later) generated art both draw from the same 32-colour set instead
 * of an unbounded one, which is what makes independently produced pieces
 * read as one coherent world. */
export function snapToPalette(color: number): number {
  const [r, g, b] = toRgb(color);
  let best = PALETTE_ENTRIES[0][1];
  let bestDist = Infinity;
  for (const [, candidate] of PALETTE_ENTRIES) {
    const [cr, cg, cb] = toRgb(candidate);
    const dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2;
    if (dist < bestDist) {
      bestDist = dist;
      best = candidate;
    }
  }
  return best;
}
