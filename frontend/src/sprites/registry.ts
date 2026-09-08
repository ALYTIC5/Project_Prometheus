/**
 * Sprite-swap layer (PROMPTS.md PROMPT 1 Part B). Every visual thing
 * resolves through resolveSprite() so Prompt 12's real art drop-in touches
 * only this manifest, never rendering code.
 *
 * Placeholder era: the manifest maps (kind, state) to a PROCEDURAL draw
 * spec (what decoration to draw with PixiJS Graphics) rather than an atlas
 * frame rect, since there are no real textures yet. Prompt 12 changes
 * ProceduralSpec's shape to an AtlasSpec -- the resolveSprite() call sites
 * in render/*.ts do not change, only what this file returns.
 *
 * Construction phase is a real visual STRUCTURE per phase, never opacity.
 * Alpha is reserved for genuine effects (fog, ghosts) -- none exist yet, so
 * every phase renders fully opaque.
 */

export type SpriteKind = 'building' | 'monument';

export type ConstructionPhase =
  | 'PLANNED'
  | 'SCAFFOLDING'
  | 'FOUNDATION'
  | 'ACTIVE'
  | 'DAMAGED'
  | 'SEALED'
  | 'OVERGROWN';

/** Footprint size class, derived from a building's real width/height
 * (1x1 = TOWER, 2x2 = MEDIUM, 3x3 = LARGE) rather than tracked separately
 * -- the backend's location is the one source of truth for footprint size. */
export type FootprintClass = 'TOWER' | 'MEDIUM' | 'LARGE';

export function classifyFootprint(width: number, height: number): FootprintClass {
  if (width === 1 && height === 1) return 'TOWER';
  if (width === 3 && height === 3) return 'LARGE';
  return 'MEDIUM';
}

export type StructuralOutline =
  | 'none'
  | 'dashed-stakes'
  | 'post-and-beam'
  | 'chains'
  | 'glow'
  | 'cracks'
  | 'vines';

export interface ProceduralSpec {
  /** Whether the building has any 3D volume at all -- PLANNED buildings
   * are ground-only outlines, everything else has real height. */
  hasVolume: boolean;
  /** Structural decoration layered on top of (or instead of) the volume. */
  outline: StructuralOutline;
  outlineColor: number;
  /** Windows lit / emissive glow -- only true for ACTIVE. */
  litWindows: boolean;
  /** Desaturate the base colour toward grey (0 = full colour, 1 = grey). */
  desaturate: number;
}

const MANIFEST: Record<ConstructionPhase, ProceduralSpec> = {
  PLANNED: {
    hasVolume: false,
    outline: 'dashed-stakes',
    outlineColor: 0x888888,
    litWindows: false,
    desaturate: 0.6,
  },
  SCAFFOLDING: {
    hasVolume: true,
    outline: 'post-and-beam',
    outlineColor: 0xcccccc,
    litWindows: false,
    desaturate: 0.2,
  },
  FOUNDATION: {
    hasVolume: true,
    outline: 'post-and-beam',
    outlineColor: 0xdddddd,
    litWindows: false,
    desaturate: 0.1,
  },
  ACTIVE: {
    hasVolume: true,
    outline: 'glow',
    outlineColor: 0xffd700,
    litWindows: true,
    desaturate: 0,
  },
  DAMAGED: {
    hasVolume: true,
    outline: 'cracks',
    outlineColor: 0xff4444,
    litWindows: false,
    desaturate: 0.1,
  },
  SEALED: {
    hasVolume: true,
    outline: 'chains',
    outlineColor: 0xff0000,
    litWindows: false,
    desaturate: 0.7,
  },
  OVERGROWN: {
    hasVolume: true,
    outline: 'vines',
    outlineColor: 0x3a5f3a,
    litWindows: false,
    desaturate: 0.5,
  },
};

/** Per-kind silhouette detail so buildings are distinguishable by shape
 * alone at zoomed-out scale (PROMPTS.md: no if(variant === "oracle")
 * anywhere outside this manifest). One entry per real building `kind`. */
export type SilhouetteFeature =
  | 'columns'
  | 'chimney'
  | 'pier'
  | 'beacon-tower'
  | 'dome'
  | 'blast-door'
  | 'stepped-obelisk'
  | 'none';

const SILHOUETTE: Record<string, SilhouetteFeature> = {
  oracle: 'columns',
  forge: 'chimney',
  harbour: 'pier',
  watchtower: 'beacon-tower',
  library: 'dome',
  vault: 'blast-door',
  monument: 'stepped-obelisk',
};

export function resolveSprite(
  kind: SpriteKind,
  variant: string,
  state: ConstructionPhase,
): ProceduralSpec {
  if (kind === 'monument') {
    // The Monument only ever renders ACTIVE (PROMPTS.md is explicit),
    // but resolve it through the same table for a uniform call site.
    return MANIFEST.ACTIVE;
  }
  return MANIFEST[state] ?? MANIFEST.PLANNED;
}

export function resolveSilhouette(kind: string): SilhouetteFeature {
  return SILHOUETTE[kind] ?? 'none';
}
