import * as PIXI from 'pixi.js';
import { Layer } from '../iso/projection';

export interface LabelCandidate {
  id: string;
  /** Anchor point, already offset upward by the caller past the
   * building's pixel height -- this module only resolves collisions. */
  x: number;
  y: number;
  text: string;
  /** Hovered or selected labels always show, regardless of zoom. */
  force: boolean;
}

function overlaps(a: PIXI.Text, b: PIXI.Text): boolean {
  const xOverlap = Math.abs(a.x - b.x) < (a.width + b.width) / 2;
  const aTop = a.y - a.height;
  const bTop = b.y - b.height;
  const yOverlap = aTop < b.y && bTop < a.y;
  return xOverlap && yOverlap;
}

/** Rebuilds the label layer from scratch each call: only hover/selected/
 * zoomed-in-enough candidates are shown (never "all labels, always" --
 * that alone is most of the fix for label collisions), and any remaining
 * overlaps are resolved by nudging the later label further from the
 * ground (away from the ground plane, not toward it, so a pushed label
 * never ends up overlapping the building it names) up to 3 times before
 * being dropped entirely. */
export function updateLabels(
  layer: PIXI.Container,
  candidates: LabelCandidate[],
  showAllZoomedIn: boolean,
): void {
  layer.removeChildren();
  layer.zIndex = Layer.LABEL;

  const visible = candidates.filter((c) => c.force || showAllZoomedIn);
  const sorted = [...visible].sort((a, b) => a.y - b.y);
  const placed: PIXI.Text[] = [];

  for (const candidate of sorted) {
    const label = new PIXI.Text({
      text: candidate.text,
      style: {
        fill: 0xeeeeee,
        fontSize: 11,
        fontFamily: 'monospace',
        stroke: { color: 0x000000, width: 2 },
      },
    });
    label.anchor.set(0.5, 1);
    label.x = candidate.x;
    label.y = candidate.y;

    let attempts = 0;
    while (attempts < 3 && placed.some((p) => overlaps(p, label))) {
      label.y -= label.height + 2;
      attempts++;
    }

    if (!placed.some((p) => overlaps(p, label))) {
      placed.push(label);
      // Dark plate behind the text, sized to its measured bounds -- the
      // "small pixel-font banner with a dark plate" the labels rewrite asks
      // for. Structural fill stays opaque (Part 1's rule); this isn't a
      // building face, but there's no reason to make an exception here.
      const plate = new PIXI.Graphics();
      const pad = 3;
      plate
        .rect(label.x - label.width / 2 - pad, label.y - label.height - pad, label.width + pad * 2, label.height + pad * 2)
        .fill({ color: 0x0a0a1a });
      layer.addChild(plate);
      layer.addChild(label);
    }
  }
}
