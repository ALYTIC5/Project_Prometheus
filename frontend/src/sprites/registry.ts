/**
 * Sprite-swap layer (PROMPTS.md PROMPT 1 Part B). Every visual thing
 * resolves through resolveSprite() so Prompt 12's real art drop-in
 * touches only this manifest, never rendering code.
 *
 * Placeholder era: the manifest maps (kind, state) to a PROCEDURAL draw
 * spec (what decoration to draw with PixiJS Graphics) rather than an
 * atlas frame rect, since there are no real textures yet. Prompt 12
 * changes ProceduralSpec's shape to an AtlasSpec (atlas name, frame
 * rect, anchor, frame count, fps) — the resolveSprite() call sites in
 * WorldView.tsx do not change, only what this file returns.
 *
 * Only "building" and "monument" kinds exist right now, because no
 * agent, hero, or prop has a real backing job/strategy yet (see
 * WorldState.agents / .districts, both always [] until later prompts).
 * Adding a kind here ahead of the backend producing real data for it
 * would be exactly the kind of decoration CLAUDE.md forbids.
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

export interface ProceduralSpec {
  /** Outline style drawn over the building's base color fill. */
  outline: 'none' | 'scaffold-lines' | 'chains' | 'glow' | 'cracks' | 'vines';
  outlineColor: number;
  /** Fill dims to this alpha for non-active buildings — a scaffolded
   * building should read as "less real" than an active one. */
  fillAlpha: number;
}

const MANIFEST: Record<ConstructionPhase, ProceduralSpec> = {
  PLANNED: { outline: 'none', outlineColor: 0x555555, fillAlpha: 0.25 },
  SCAFFOLDING: { outline: 'scaffold-lines', outlineColor: 0xaaaaaa, fillAlpha: 0.45 },
  FOUNDATION: { outline: 'scaffold-lines', outlineColor: 0xcccccc, fillAlpha: 0.65 },
  ACTIVE: { outline: 'glow', outlineColor: 0xffd700, fillAlpha: 1.0 },
  DAMAGED: { outline: 'cracks', outlineColor: 0xff4444, fillAlpha: 0.85 },
  SEALED: { outline: 'chains', outlineColor: 0xff0000, fillAlpha: 0.9 },
  OVERGROWN: { outline: 'vines', outlineColor: 0x3a5f3a, fillAlpha: 0.6 },
};

export function resolveSprite(
  kind: SpriteKind,
  _variant: string,
  state: ConstructionPhase,
): ProceduralSpec {
  if (kind === 'monument') {
    // The Monument only ever renders ACTIVE (PROMPTS.md is explicit),
    // but resolve it through the same table for a uniform call site.
    return MANIFEST.ACTIVE;
  }
  return MANIFEST[state] ?? MANIFEST.PLANNED;
}
