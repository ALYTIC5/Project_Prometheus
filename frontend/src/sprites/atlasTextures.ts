import * as PIXI from 'pixi.js';
import { isProduction, type AtlasSpec } from './registry';

/** Atlas PNGs live under public/ (not src/sprites/), so they're fetchable
 * by plain URL under Next's static export -- see tools/art/common.py's
 * PUBLIC_SPRITES_DIR comment for why this can't be a webpack asset import. */
const ATLAS_URLS = ['/sprites/buildings_atlas.png', '/sprites/terrain_atlas.png'];

const baseTextures = new Map<string, PIXI.Texture>();
const frameCache = new Map<string, PIXI.Texture>();

/** Loads every atlas PNG once, nearest-neighbour filtered (PROMPTS.md:
 * "nearest-neighbour filtering, mipmaps off (pixel art)"). No-op on the
 * placeholder path so dev/CI never fetches atlas PNGs. Call once, before
 * any drawBuilding/drawGround call that might resolve an AtlasSpec. */
export async function loadAtlasTextures(): Promise<void> {
  if (!isProduction() || baseTextures.size > 0) return;
  for (const url of ATLAS_URLS) {
    const filename = url.split('/').pop()!;
    const texture = await PIXI.Assets.load<PIXI.Texture>({
      src: url,
      data: { scaleMode: 'nearest' },
    });
    texture.source.scaleMode = 'nearest';
    baseTextures.set(filename, texture);
  }
}

/** Resolves an AtlasSpec's frame to a cached sub-Texture of its atlas, or
 * null if textures aren't loaded yet or the spec has no atlas frame --
 * callers must fall back to procedural drawing in that case. */
export function getAtlasFrame(spec: AtlasSpec): PIXI.Texture | null {
  if (!spec.atlas || !spec.frame) return null;
  const key = `${spec.atlas}:${spec.frame.x},${spec.frame.y},${spec.frame.width},${spec.frame.height}`;
  const cached = frameCache.get(key);
  if (cached) return cached;

  const base = baseTextures.get(spec.atlas);
  if (!base) return null;

  const texture = new PIXI.Texture({
    source: base.source,
    frame: new PIXI.Rectangle(spec.frame.x, spec.frame.y, spec.frame.width, spec.frame.height),
  });
  frameCache.set(key, texture);
  return texture;
}
