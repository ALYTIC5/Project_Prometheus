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

export type SpriteKind = 'building' | 'monument' | 'agent';

export type ConstructionPhase =
  | 'PLANNED'
  | 'SCAFFOLDING'
  | 'FOUNDATION'
  | 'ACTIVE'
  | 'DAMAGED'
  | 'SEALED'
  | 'OVERGROWN';

export const CONSTRUCTION_PHASES: ConstructionPhase[] = [
  'PLANNED', 'SCAFFOLDING', 'FOUNDATION', 'ACTIVE', 'DAMAGED', 'SEALED', 'OVERGROWN',
];

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

export interface AtlasSpec {
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
  /** Atlas filename (when SPRITE_SET=production). */
  atlas?: string;
  /** Frame rect in the atlas (when SPRITE_SET=production). */
  frame?: { x: number; y: number; width: number; height: number };
  /** Anchor point (when SPRITE_SET=production). */
  anchor?: { x: number; y: number };
  /** Frame count for animated sprites (when SPRITE_SET=production). */
  frameCount?: number;
  /** Frames per second (when SPRITE_SET=production). */
  fps?: number;
}

export type SpriteSpec = ProceduralSpec | AtlasSpec;

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
  | 'oval-tiers'
  | 'colonnade'
  | 'buttressed-hall'
  | 'sunken-ruin'
  | 'ziggurat'
  | 'stepped-obelisk'
  | 'none';

const SILHOUETTE: Record<string, SilhouetteFeature> = {
  oracle: 'columns',
  forge: 'chimney',
  harbour: 'pier',
  watchtower: 'beacon-tower',
  library: 'dome',
  vault: 'blast-door',
  arena: 'oval-tiers',
  treasury: 'colonnade',
  archive: 'buttressed-hall',
  underworld: 'sunken-ruin',
  temple: 'ziggurat',
  monument: 'stepped-obelisk',
};

/** Storeys per real building `kind`, driving pixel height in
 * render/building.ts -- not a flat per-footprint-class constant, so a
 * LARGE 3x3 building at 6 storeys (Oracle) reads as visibly taller than
 * it is wide, per the world-renderer verticality pass. The Monument is
 * handled separately in render/monument.ts (its height is driven by the
 * real benchmark equity, not a fixed storey count). */
export const STOREYS: Record<string, number> = {
  library: 3,
  archive: 2,
  underworld: 2,
  temple: 4,
  harbour: 2,
  forge: 4,
  oracle: 6,
  arena: 3,
  treasury: 4,
  watchtower: 8,
  vault: 3,
};

export const STOREY_PIXEL_HEIGHT = 22;

/** Deterministic string hash (not Math.random) -- stable across renders,
 * used to pick a per-building lit-window pattern, work activity, etc.
 * without persisting any state. */
export function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) hash = (hash * 31 + value.charCodeAt(i)) | 0;
  return Math.abs(hash);
}

/** Agent roles used by the sprite manifest. */
export type AgentRole =
  | 'builder' | 'scribe' | 'engineer' | 'experimenter' | 'statistician'
  | 'guardian' | 'auditor' | 'necromancer' | 'scholar' | 'prophet';

/** Build state derived from backend `construction_phase` field. */
export type AgentAction = 'idle' | 'walk' | 'work' | 'carry';

/** Agent sprite semantic key: `${role}_${action}_r${rotation}` */
export type AgentSpriteKey = `${AgentRole}_${AgentAction}`;

/** Current SPRITE_SET -- 'placeholder' uses ProceduralSpec, 'production' uses AtlasSpec.
 *  Set at build time via NEXT_PUBLIC_SPRITE_SET env var. */
const SPRITE_SET: string =
  typeof window !== 'undefined'
    ? (window as any).__SPRITE_SET__ ?? 'placeholder'
    : 'placeholder';

/** Load production manifest if SPRITE_SET=production and the file exists. */
let productionManifest: Record<string, AtlasSpec> | null = null;

function loadProductionManifest(): Record<string, AtlasSpec> | null {
  if (SPRITE_SET !== 'production') return null;
  try {
    // Dynamic import for production manifest -- loaded at build time
    const mod = require('./manifest.production.json');
    return mod as Record<string, AtlasSpec>;
  } catch {
    console.warn('Could not load manifest.production.json -- falling back to placeholder');
    return null;
  }
}

productionManifest = loadProductionManifest();

/** Resolve to an AtlasSpec when SPRITE_SET=production, otherwise ProceduralSpec. */
export function resolveSprite(
  kind: SpriteKind,
  variant: string,
  state: ConstructionPhase,
): SpriteSpec {
  if (kind === 'monument') {
    return MANIFEST.ACTIVE;
  }
  // If production manifest is loaded, try to return an AtlasSpec
  if (productionManifest) {
    const phaseKey = state.toLowerCase();
    const key = `${variant}_${phaseKey}`;
    if (productionManifest[key]) {
      const spec = productionManifest[key];
      // Merge procedural spec fields from MANIFEST with atlas data
      const procSpec = MANIFEST[state] ?? MANIFEST.PLANNED;
      return { ...spec, ...procSpec };
    }
  }
  return MANIFEST[state] ?? MANIFEST.PLANNED;
}

export function resolveAgentSprite(
  role: AgentRole,
  action: AgentAction,
  rotation: number,
): AtlasSpec | null {
  if (!productionManifest) return null;
  const key = `${role}_${action}_r${rotation}`;
  return productionManifest[key] ?? null;
}

/** Terrain sprite keys with real atlas art (see manifest.production.json's
 * terrain_* entries) -- ground.ts hashes over these for the default tile
 * fill and picks 'terrain_cobblestone' for the plaza; water and roads have
 * no matching art and stay procedural. */
export function resolveTerrainSprite(key: string): AtlasSpec | null {
  if (!productionManifest) return null;
  return productionManifest[key] ?? null;
}

export function isProduction(): boolean {
  return SPRITE_SET === 'production';
}

export function resolveSilhouette(kind: string): SilhouetteFeature {
  return SILHOUETTE[kind] ?? 'none';
}
