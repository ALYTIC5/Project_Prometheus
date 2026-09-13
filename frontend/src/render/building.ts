import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';
import { snapToPalette } from '../sprites/palette';
import { getAtlasFrame } from '../sprites/atlasTextures';
import {
  STOREYS,
  STOREY_PIXEL_HEIGHT,
  classifyFootprint,
  hashString,
  resolveSilhouette,
  resolveSprite,
  type AtlasSpec,
  type ConstructionPhase,
} from '../sprites/registry';
import type { Building } from '../types';

/** Darkens (or lightens, for negative values) a colour toward black/white,
 * with a small warm (+) or cool (-) hue nudge -- `warmth` shifts the
 * red/blue balance slightly after the value change, for the top-left
 * light source's warm-lit / cool-shadow split. */
function shade(color: number, darken: number, warmth = 0): number {
  const r = (color >> 16) & 0xff;
  const g = (color >> 8) & 0xff;
  const b = color & 0xff;
  const f = 1 - darken;
  const clamp = (v: number) => Math.max(0, Math.min(255, v));
  const nr = clamp(r * f + warmth * 10);
  const ng = clamp(g * f);
  const nb = clamp(b * f - warmth * 10);
  return (Math.round(nr) << 16) | (Math.round(ng) << 8) | Math.round(nb);
}

function desaturate(color: number, amount: number): number {
  const r = (color >> 16) & 0xff;
  const g = (color >> 8) & 0xff;
  const b = color & 0xff;
  const gray = 0.3 * r + 0.59 * g + 0.11 * b;
  const mix = (c: number) => Math.round(c + (gray - c) * amount);
  return (mix(r) << 16) | (mix(g) << 8) | mix(b);
}

function hexToNumber(hex: string): number {
  return parseInt(hex.replace('#', ''), 16);
}

function heightFor(kind: string): number {
  const storeys = STOREYS[kind] ?? 2;
  return storeys * STOREY_PIXEL_HEIGHT;
}

/** Draws one building as an opaque isometric volume: top face (full
 * value), left face (68% value, cool-shifted), right face (48% value,
 * warm-shifted) for a consistent top-left light source -- never alpha.
 * Height comes from a real per-kind storeys lookup (registry.ts), not a
 * flat per-footprint-class constant, so a LARGE building at 6 storeys
 * (Oracle) reads as visibly taller than it is wide. Construction phase and
 * building kind add real structural decoration on top, resolved entirely
 * through sprites/registry.ts. Labels are NOT drawn here -- see
 * render/labels.ts. */
export function drawBuilding(building: Building): PIXI.Container {
  const container = new PIXI.Container();
  const { location } = building;
  const anchor = gridToScreen(location.x + location.width / 2, location.y + location.height / 2);
  container.x = anchor.x;
  container.y = anchor.y;
  container.zIndex = depthOf(location.x, location.y, location.width, location.height, Layer.BUILDING);
  container.eventMode = 'static';
  container.cursor = 'pointer';
  (container as PIXI.Container & { __buildingId: string }).__buildingId = building.id;

  const phase = building.phase.toUpperCase() as ConstructionPhase;
  const spec = resolveSprite('building', building.kind, phase);
  const footprintClass = classifyFootprint(location.width, location.height);
  const silhouette = resolveSilhouette(building.kind);

  const halfW = (location.width * TILE_WIDTH) / 2;
  const halfH = TILE_HEIGHT * (location.height * 0.5 + 0.4);
  const baseColor = desaturate(snapToPalette(hexToNumber(building.color)), spec.desaturate);
  const height = heightFor(building.kind);

  const atlasTexture = 'atlas' in spec ? getAtlasFrame(spec as AtlasSpec) : null;
  if (atlasTexture) {
    const atlasSpec = spec as AtlasSpec;
    const sprite = new PIXI.Sprite(atlasTexture);
    sprite.anchor.set(
      atlasSpec.anchor!.x / atlasSpec.frame!.width,
      atlasSpec.anchor!.y / atlasSpec.frame!.height,
    );
    container.addChild(sprite);

    // Only DAMAGED/SEALED/OVERGROWN need a procedural overlay: pack_atlas.py
    // falls those back to the kind's own ACTIVE frame rather than painting
    // per-kind cracks/chains/vines art, so the overlay is what actually
    // distinguishes them on screen. Every other phase (including PLANNED's
    // ground-only look and SCAFFOLDING's poles) has its own dedicated frame
    // already painted in -- a procedural dashed-stakes/post-and-beam/glow
    // overlay sized for the procedural volume would just misalign with it.
    const g = new PIXI.Graphics();
    switch (spec.outline) {
      case 'cracks':
        g.moveTo(-halfW * 0.3, -height * 0.8).lineTo(0, -height * 0.4).lineTo(-halfW * 0.15, 0).stroke({
          color: spec.outlineColor,
          width: 1.5,
        });
        g.circle(0, -height - halfH - 10, 4).fill({ color: 0x888888, alpha: 0.5 });
        g.circle(6, -height - halfH - 18, 5).fill({ color: 0x999999, alpha: 0.35 });
        break;
      case 'chains':
        g.moveTo(-halfW, -height * 0.7).lineTo(halfW, -height * 0.2).stroke({ color: spec.outlineColor, width: 2 });
        g.moveTo(-halfW, -height * 0.2).lineTo(halfW, -height * 0.7).stroke({ color: spec.outlineColor, width: 2 });
        g.circle(0, -height * 0.45, 5).stroke({ color: spec.outlineColor, width: 2 });
        break;
      case 'vines':
        for (let i = -1; i <= 1; i += 2) {
          g.moveTo(i * halfW * 0.6, 0);
          for (let s = 1; s <= 4; s++) {
            g.lineTo(i * halfW * 0.6 + (s % 2 === 0 ? 4 : -4), -height * (s / 4));
          }
          g.stroke({ color: spec.outlineColor, width: 1.5 });
        }
        break;
      default:
        break;
    }
    container.addChild(g);
    return container;
  }

  const g = new PIXI.Graphics();

  if (!spec.hasVolume) {
    // PLANNED: ground-only dashed footprint outline + corner stakes. No volume.
    const corners: [number, number][] = [
      [0, -halfH],
      [halfW, 0],
      [0, halfH],
      [-halfW, 0],
    ];
    for (let i = 0; i < corners.length; i++) {
      const [x1, y1] = corners[i];
      const [x2, y2] = corners[(i + 1) % corners.length];
      const segments = 6;
      for (let s = 0; s < segments; s += 2) {
        const t0 = s / segments;
        const t1 = (s + 1) / segments;
        g.moveTo(x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0);
        g.lineTo(x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1);
      }
      g.stroke({ color: spec.outlineColor, width: 1.5 });
    }
    for (const [cx, cy] of corners) {
      g.moveTo(cx, cy).lineTo(cx, cy - 6).stroke({ color: spec.outlineColor, width: 1.5 });
    }
    container.addChild(g);
    return container;
  }

  // Opaque volume: top diamond roof + two shaded side faces. Arena is the
  // one kind that skips the flat roof entirely (see 'oval-tiers' below).
  if (silhouette !== 'oval-tiers') {
    g.poly([0, -height - halfH, halfW, -height, 0, -height + halfH, -halfW, -height]).fill({
      color: baseColor,
    });
  }
  g.poly([-halfW, -height, 0, -height + halfH, 0, halfH, -halfW, 0]).fill({
    color: shade(baseColor, 0.32, -1),
  });
  g.poly([halfW, -height, 0, -height + halfH, 0, halfH, halfW, 0]).fill({
    color: shade(baseColor, 0.52, 1),
  });

  if (spec.litWindows) {
    const rows = footprintClass === 'TOWER' ? 3 : Math.max(2, Math.round(height / 40));
    const patternSeed = hashString(building.id);
    let slot = 0;
    for (let r = 0; r < rows; r++) {
      const wy = -height + halfH + 10 + r * 14;
      for (const wx of [-halfW * 0.4, halfW * 0.15]) {
        const lit = ((patternSeed >> slot) & 1) === 0;
        slot++;
        if (lit) {
          g.rect(wx, wy, halfW * 0.25, 8).fill({ color: 0xfff4c2 });
        }
      }
    }
  }

  switch (spec.outline) {
    case 'post-and-beam': {
      const solid = building.phase.toUpperCase() === 'FOUNDATION';
      const poles: [number, number][] = [
        [-halfW, 0],
        [-halfW, -height],
        [halfW, 0],
        [halfW, -height],
      ];
      for (let i = 0; i < poles.length; i += 2) {
        g.moveTo(poles[i][0], poles[i][1]).lineTo(poles[i + 1][0], poles[i + 1][1]).stroke({
          color: spec.outlineColor,
          width: 2,
        });
      }
      const beamY = solid ? -height * 0.4 : -height * 0.6;
      g.moveTo(-halfW, beamY).lineTo(halfW, beamY).stroke({ color: spec.outlineColor, width: 1.5 });
      if (solid) {
        g.rect(-halfW, 0, halfW * 2, -height * 0.4).fill({ color: shade(baseColor, 0.1) });
      }
      break;
    }
    case 'glow':
      g.poly([0, -height - halfH - 3, halfW + 3, -height, 0, -height + halfH + 3, -halfW - 3, -height]).stroke({
        color: spec.outlineColor,
        width: 1.5,
      });
      break;
    case 'cracks':
      g.moveTo(-halfW * 0.3, -height * 0.8).lineTo(0, -height * 0.4).lineTo(-halfW * 0.15, 0).stroke({
        color: spec.outlineColor,
        width: 1.5,
      });
      g.circle(0, -height - halfH - 10, 4).fill({ color: 0x888888, alpha: 0.5 });
      g.circle(6, -height - halfH - 18, 5).fill({ color: 0x999999, alpha: 0.35 });
      break;
    case 'chains':
      g.moveTo(-halfW, -height * 0.7).lineTo(halfW, -height * 0.2).stroke({ color: spec.outlineColor, width: 2 });
      g.moveTo(-halfW, -height * 0.2).lineTo(halfW, -height * 0.7).stroke({ color: spec.outlineColor, width: 2 });
      g.circle(0, -height * 0.45, 5).stroke({ color: spec.outlineColor, width: 2 });
      break;
    case 'vines':
      for (let i = -1; i <= 1; i += 2) {
        g.moveTo(i * halfW * 0.6, 0);
        for (let s = 1; s <= 4; s++) {
          g.lineTo(i * halfW * 0.6 + (s % 2 === 0 ? 4 : -4), -height * (s / 4));
        }
        g.stroke({ color: spec.outlineColor, width: 1.5 });
      }
      break;
    default:
      break;
  }

  switch (silhouette) {
    case 'columns': {
      // Oracle: stepped pediment + 6 front columns + a glowing rune disc.
      for (let i = 0; i < 6; i++) {
        const cx = -halfW * 0.7 + (i * halfW * 1.4) / 5;
        g.moveTo(cx, 0).lineTo(cx, -height * 0.85).stroke({ color: 0xffffff, width: 2 });
      }
      g.poly([-halfW * 0.6, -height * 0.85, halfW * 0.6, -height * 0.85, 0, -height * 1.05]).fill({
        color: shade(baseColor, 0.1),
      });
      g.circle(0, -height * 0.95, 6).stroke({ color: 0xffd27a, width: 1.5 });
      break;
    }
    case 'chimney':
      // Forge: chimney + ember emitter + glowing furnace mouth.
      g.rect(halfW * 0.3, -height - halfH - 22, 8, 22).fill({ color: shade(baseColor, 0.3) });
      g.circle(halfW * 0.3 + 4, -height - halfH - 26, 3).fill({ color: 0xff8844 });
      g.rect(-halfW * 0.25, -14, halfW * 0.4, 10).fill({ color: 0xff5522 });
      break;
    case 'pier':
      // Harbour: pier plank over water + 2 crane arms + moored-hull outline.
      g.rect(-halfW * 1.6, halfH * 0.4, halfW * 1.4, 5).fill({ color: 0x6b4a2f });
      g.moveTo(halfW * 0.6, -height * 0.7).lineTo(halfW * 1.3, -height * 0.7).stroke({ color: 0x999999, width: 2 });
      g.moveTo(halfW * 0.6, -height * 0.5).lineTo(halfW * 1.1, -height * 0.5).stroke({ color: 0x999999, width: 2 });
      g.moveTo(-halfW * 1.4, halfH * 0.5).lineTo(-halfW * 0.8, halfH * 0.5).lineTo(-halfW * 0.8, halfH * 0.3).stroke({
        color: 0x334455,
        width: 1.5,
      });
      break;
    case 'beacon-tower': {
      // Watchtower: tapering profile + railed platform + pulsing beacon.
      g.moveTo(-halfW * 0.3, 0).lineTo(-halfW * 0.15, -height).lineTo(halfW * 0.15, -height).lineTo(halfW * 0.3, 0).stroke({
        color: shade(baseColor, 0.1),
        width: 1,
      });
      g.moveTo(-halfW * 0.25, -height * 0.9).lineTo(halfW * 0.25, -height * 0.9).stroke({ color: 0xcccccc, width: 1.5 });
      g.circle(0, -height - halfH - 8, 5).fill({ color: 0xff5555 });
      break;
    }
    case 'dome':
      // Library: dome + arched windows + entry stair.
      g.ellipse(0, -height - halfH, halfW * 0.4, 12).fill({ color: shade(baseColor, 0.15) });
      for (const wx of [-halfW * 0.35, halfW * 0.15]) {
        g.arc(wx + halfW * 0.1, -height * 0.5, halfW * 0.12, Math.PI, 0).fill({ color: 0xfff4c2 });
      }
      g.rect(-halfW * 0.3, 0, halfW * 0.6, 4).fill({ color: shade(baseColor, 0.2) });
      break;
    case 'blast-door':
      // Vault: blast-door face + buttress fins (chains already drawn above).
      g.rect(-halfW * 0.5, -height * 0.7, halfW, height * 0.6).fill({ color: shade(baseColor, 0.4) });
      g.circle(0, -height * 0.4, 8).stroke({ color: 0xcccccc, width: 2 });
      g.rect(-halfW - 3, -height * 0.6, 4, height * 0.5).fill({ color: shade(baseColor, 0.2) });
      g.rect(halfW - 1, -height * 0.6, 4, height * 0.5).fill({ color: shade(baseColor, 0.2) });
      break;
    case 'oval-tiers': {
      // Arena: open-topped oval tiers instead of a flat roof.
      const tiers = 3;
      for (let t = 0; t < tiers; t++) {
        const ty = -height * (t / tiers);
        const w = halfW * (1 - t * 0.15);
        g.ellipse(0, ty, w, TILE_HEIGHT * 0.3).stroke({ color: shade(baseColor, t * 0.15), width: 3 });
      }
      break;
    }
    case 'colonnade':
      // Treasury: colonnade + pitched roof already drawn + coin props.
      for (let i = 0; i < 4; i++) {
        const cx = -halfW * 0.6 + (i * halfW * 1.2) / 3;
        g.moveTo(cx, 0).lineTo(cx, -height * 0.6).stroke({ color: 0xf5e6c8, width: 1.5 });
      }
      g.circle(halfW * 0.4, 4, 4).fill({ color: 0xf1c40f });
      g.circle(halfW * 0.5, 2, 3).fill({ color: 0xf1c40f });
      break;
    case 'buttressed-hall':
      // Archive: long low hall, regular buttresses, narrow slit windows.
      for (let i = -1; i <= 1; i++) {
        const cx = i * halfW * 0.6;
        g.rect(cx - 1, -height * 0.7, 2, height * 0.6).fill({ color: shade(baseColor, 0.15) });
        g.rect(cx - 3, -height * 0.35, 6, 12).fill({ color: 0x223344 });
      }
      break;
    case 'sunken-ruin':
      // Underworld: jagged broken roofline + cold blue glow low on the front.
      g.poly([-halfW * 0.5, -height, -halfW * 0.2, -height * 1.15, 0, -height * 0.95, halfW * 0.3, -height * 1.1, halfW * 0.5, -height]).stroke({
        color: 0x445566,
        width: 1.5,
      });
      g.rect(-halfW * 0.3, -18, halfW * 0.6, 10).fill({ color: 0x2255aa });
      break;
    case 'ziggurat': {
      // Temple: stepped ziggurat tiers + a brazier on top.
      const tiers = 3;
      for (let t = 0; t < tiers; t++) {
        const tierH = (height * 0.8) / tiers;
        const y0 = -t * tierH;
        const w = halfW * (1 - t * 0.2);
        g.rect(-w, y0 - tierH, w * 2, tierH * 0.15).fill({ color: shade(baseColor, t * 0.1) });
      }
      g.circle(0, -height - halfH - 6, 4).fill({ color: 0xff8844 });
      break;
    }
    default:
      break;
  }

  container.addChild(g);
  return container;
}
