import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';
import {
  classifyFootprint,
  resolveSilhouette,
  resolveSprite,
  type ConstructionPhase,
} from '../sprites/registry';
import type { Building } from '../types';

const VOLUME_STOREY_HEIGHT = 34;

function shade(color: number, darken: number): number {
  const r = (color >> 16) & 0xff;
  const g = (color >> 8) & 0xff;
  const b = color & 0xff;
  const f = 1 - darken;
  return (Math.round(r * f) << 16) | (Math.round(g * f) << 8) | Math.round(b * f);
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

/** Draws one building as an opaque isometric volume: top face, left face
 * (darkened ~20%), right face (darkened ~35%) for a consistent top-left
 * light source -- never alpha. Construction phase and building kind add
 * real structural decoration on top, resolved entirely through
 * sprites/registry.ts (no per-kind branching here beyond reading its
 * output). Labels are NOT drawn here -- see render/labels.ts. */
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
  const baseColor = desaturate(hexToNumber(building.color), spec.desaturate);
  const height = footprintClass === 'TOWER' ? VOLUME_STOREY_HEIGHT * 3 : VOLUME_STOREY_HEIGHT * 1.4;

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
      g.stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.8 });
    }
    for (const [cx, cy] of corners) {
      g.moveTo(cx, cy).lineTo(cx, cy - 6).stroke({ color: spec.outlineColor, width: 1.5 });
    }
    container.addChild(g);
    return container;
  }

  // Opaque volume: top diamond roof + two shaded side faces.
  g.poly([0, -height - halfH, halfW, -height, 0, -height + halfH, -halfW, -height]).fill({
    color: baseColor,
  });
  g.poly([-halfW, -height, 0, -height + halfH, 0, halfH, -halfW, 0]).fill({
    color: shade(baseColor, 0.2),
  });
  g.poly([halfW, -height, 0, -height + halfH, 0, halfH, halfW, 0]).fill({
    color: shade(baseColor, 0.35),
  });

  if (spec.litWindows) {
    const rows = footprintClass === 'TOWER' ? 3 : 2;
    for (let r = 0; r < rows; r++) {
      const wy = -height + halfH + 10 + r * 14;
      g.rect(-halfW * 0.4, wy, halfW * 0.25, 8).fill({ color: 0xfff4c2, alpha: 0.9 });
      g.rect(halfW * 0.15, wy, halfW * 0.25, 8).fill({ color: 0xfff4c2, alpha: 0.9 });
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
          alpha: 0.9,
        });
      }
      const beamY = solid ? -height * 0.4 : -height * 0.6;
      g.moveTo(-halfW, beamY).lineTo(halfW, beamY).stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.8 });
      if (solid) {
        g.rect(-halfW, 0, halfW * 2, -height * 0.4).fill({ color: shade(baseColor, 0.1), alpha: 0.5 });
      }
      break;
    }
    case 'glow':
      g.poly([0, -height - halfH - 3, halfW + 3, -height, 0, -height + halfH + 3, -halfW - 3, -height]).stroke({
        color: spec.outlineColor,
        width: 1.5,
        alpha: 0.9,
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
        g.stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.8 });
      }
      break;
    default:
      break;
  }

  switch (silhouette) {
    case 'columns':
      for (const cx of [-halfW * 0.4, 0, halfW * 0.4]) {
        g.moveTo(cx, 0).lineTo(cx, -height * 0.9).stroke({ color: 0xffffff, width: 2, alpha: 0.6 });
      }
      g.poly([-halfW * 0.5, -height * 0.9, halfW * 0.5, -height * 0.9, 0, -height * 1.1]).fill({
        color: shade(baseColor, 0.1),
      });
      break;
    case 'chimney':
      g.rect(halfW * 0.3, -height - halfH - 20, 8, 20).fill({ color: shade(baseColor, 0.3) });
      g.circle(halfW * 0.3 + 4, -height - halfH - 24, 3).fill({ color: 0xff8844, alpha: 0.8 });
      break;
    case 'pier':
      g.rect(-halfW, halfH * 0.5, halfW * 2, 5).fill({ color: 0x6b4a2f });
      g.moveTo(halfW * 0.6, -height * 0.6).lineTo(halfW * 1.3, -height * 0.6).stroke({ color: 0x999999, width: 2 });
      break;
    case 'beacon-tower':
      g.circle(0, -height - halfH - 8, 5).fill({ color: 0xff5555, alpha: 0.9 });
      break;
    case 'dome':
      g.ellipse(0, -height - halfH, halfW * 0.4, 12).fill({ color: shade(baseColor, 0.15) });
      break;
    case 'blast-door':
      g.rect(-halfW * 0.5, -height * 0.7, halfW, height * 0.6).fill({ color: shade(baseColor, 0.4) });
      g.circle(0, -height * 0.4, 8).stroke({ color: 0xcccccc, width: 2 });
      break;
    default:
      break;
  }

  container.addChild(g);
  return container;
}
