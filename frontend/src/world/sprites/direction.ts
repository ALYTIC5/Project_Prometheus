/**
 * Compass rotation index for character sprites -- the frontend twin of
 * tools/art/import_pixellab.py's ROTATION_INDEX. r0=south ... r7=south-west,
 * PixelLab's own naming order. Both sides are hand-kept in sync (like
 * palette.ts/common.py's snap_to_palette) rather than sharing one file,
 * since they run in different languages/processes.
 *
 * Only `directionIndexFor` is used today -- every character currently on
 * screen is static (no movement yet, see docs/WORLD_MAPPING.md), so callers
 * pass a fixed heading (toward the Monument) rather than a live velocity.
 * Hysteresis on the 45-degree boundaries is deliberately not implemented:
 * there is nothing to flicker between yet.
 */

export const ROTATION_COUNT = 8;

/** Screen-space heading (dx, dy in screen pixels, +x right / +y down) ->
 * rotation index 0-7. Rounds to the nearest of 8 compass octants. */
export function directionIndexFor(dx: number, dy: number): number {
  if (dx === 0 && dy === 0) return 0; // south -- an arbitrary but deterministic default
  const angle = Math.atan2(dy, dx); // screen-space: 0 = east, +pi/2 = south
  // ROTATION_INDEX's order (south -> south-east -> east -> north-east ->
  // north -> north-west -> west -> south-west) runs in *decreasing* atan2
  // angle starting from south (+pi/2), not increasing -- south-east is at
  // +pi/4, i.e. angle went DOWN from south, not up.
  const fromSouth = Math.PI / 2 - angle;
  const octant = Math.round(fromSouth / (Math.PI / 4));
  return ((octant % ROTATION_COUNT) + ROTATION_COUNT) % ROTATION_COUNT;
}
