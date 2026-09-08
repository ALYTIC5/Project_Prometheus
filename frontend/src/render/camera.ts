import * as PIXI from 'pixi.js';
import { gridToScreen } from '../iso/projection';
import { GRID_SIZE } from './ground';

// Generous screen-space bounding box for the 26x26 iso grid, used to clamp
// panning so the city can't be dragged off screen entirely.
const GRID_HALF_WIDTH = (GRID_SIZE * 64) / 2 + 200;
const GRID_HALF_HEIGHT = (GRID_SIZE * 32) / 2 + 200;
// The grid's actual iso diamond extent (no pan-clamp margin), used for the
// fit-to-bounds default zoom.
const CITY_WIDTH = GRID_SIZE * 64;
const CITY_HEIGHT = GRID_SIZE * 32;
const FIT_FRACTION = 0.85;

const IDLE_DELAY_MS = 4000;
const DRIFT_AMPLITUDE_PX = 2;
const DRIFT_PERIOD_MS = 10000;

export interface CameraHandle {
  /** Detaches all listeners. Call on unmount. */
  destroy: () => void;
  reset: () => void;
  focusOn: (gridX: number, gridY: number) => void;
  getZoom: () => number;
}

/** A camera is a single transform (x, y, scale) applied to `world` before
 * drawing, per the camera-pan-zoom-controls pattern: drag pans, wheel
 * zooms toward the cursor (not the screen centre), and the result is
 * clamped to map bounds and snapped to whole pixels so pixel art doesn't
 * shimmer. Picking (render/selection.ts) inverts this exact transform via
 * Pixi's own Container.toLocal(), so there is only one transform to keep
 * in sync.
 *
 * The default zoom fits the city to ~85% of the viewport (computed from
 * the real screen size at reset() time, not a fixed constant), and
 * min/max zoom are relative to that computed default rather than absolute
 * numbers, so the clamp scales sensibly across viewport sizes. */
export function attachCamera(app: PIXI.Application, world: PIXI.Container): CameraHandle {
  let defaultZoom = 1;
  let minZoom = 0.5;
  let maxZoom = 3;
  let scale = defaultZoom;
  let dragging = false;
  let lastPointer = { x: 0, y: 0 };

  let lastInteraction = performance.now();
  let driftX = 0;
  let driftY = 0;

  function computeFit(): void {
    defaultZoom = Math.min(
      (app.screen.width * FIT_FRACTION) / CITY_WIDTH,
      (app.screen.height * FIT_FRACTION) / CITY_HEIGHT,
    );
    minZoom = defaultZoom * 0.5;
    maxZoom = defaultZoom * 3;
  }

  /** Snaps to the nearest of a small step table scaled by the computed
   * default zoom, so pixel art stays crisp at "round" zoom levels instead
   * of a continuous value. */
  function snapZoom(value: number): number {
    const steps = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3].map((s) => s * defaultZoom);
    let closest = steps[0];
    let bestDist = Infinity;
    for (const step of steps) {
      const dist = Math.abs(value - step);
      if (dist < bestDist) {
        bestDist = dist;
        closest = step;
      }
    }
    return closest;
  }

  function clearDrift(): void {
    world.x -= driftX;
    world.y -= driftY;
    driftX = 0;
    driftY = 0;
  }

  function noteInteraction(): void {
    clearDrift();
    lastInteraction = performance.now();
  }

  function clamp(): void {
    scale = Math.min(maxZoom, Math.max(minZoom, scale));
    const viewHalfW = app.screen.width / 2;
    const viewHalfH = app.screen.height / 2;
    const minX = viewHalfW - GRID_HALF_WIDTH * scale;
    const maxX = GRID_HALF_WIDTH * scale - viewHalfW + app.screen.width;
    const minY = viewHalfH - GRID_HALF_HEIGHT * scale;
    const maxY = GRID_HALF_HEIGHT * scale - viewHalfH + app.screen.height;
    world.x = Math.round(Math.min(Math.max(world.x, Math.min(minX, maxX)), Math.max(minX, maxX)));
    world.y = Math.round(Math.min(Math.max(world.y, Math.min(minY, maxY)), Math.max(minY, maxY)));
    world.scale.set(scale);
  }

  function reset(): void {
    computeFit();
    scale = defaultZoom;
    world.x = app.screen.width / 2;
    world.y = app.screen.height / 2 - 60;
    clamp();
  }

  function focusOn(gridX: number, gridY: number): void {
    noteInteraction();
    const { x, y } = gridToScreen(gridX, gridY);
    world.x = app.screen.width / 2 - x * scale;
    world.y = app.screen.height / 2 - y * scale;
    clamp();
  }

  function getZoom(): number {
    return scale;
  }

  function onPointerDown(e: PIXI.FederatedPointerEvent): void {
    noteInteraction();
    dragging = true;
    lastPointer = { x: e.global.x, y: e.global.y };
  }

  function onPointerMove(e: PIXI.FederatedPointerEvent): void {
    if (!dragging) return;
    lastInteraction = performance.now();
    world.x += e.global.x - lastPointer.x;
    world.y += e.global.y - lastPointer.y;
    lastPointer = { x: e.global.x, y: e.global.y };
    clamp();
  }

  function onPointerUp(): void {
    dragging = false;
  }

  function onWheel(e: WheelEvent): void {
    e.preventDefault();
    noteInteraction();
    const rect = app.canvas.getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;
    // Zoom toward the cursor: keep the world point under it stationary.
    const worldXBefore = (cursorX - world.x) / scale;
    const worldYBefore = (cursorY - world.y) / scale;
    scale = snapZoom(scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15));
    scale = Math.min(maxZoom, Math.max(minZoom, scale));
    world.x = cursorX - worldXBefore * scale;
    world.y = cursorY - worldYBefore * scale;
    clamp();
  }

  function onTick(): void {
    const now = performance.now();
    if (now - lastInteraction <= IDLE_DELAY_MS) return;
    const t = (now - lastInteraction - IDLE_DELAY_MS) / 1000;
    const phase = (t * 2 * Math.PI) / (DRIFT_PERIOD_MS / 1000);
    const newDriftX = Math.sin(phase) * DRIFT_AMPLITUDE_PX;
    const newDriftY = Math.cos(phase) * DRIFT_AMPLITUDE_PX * 0.5;
    world.x += newDriftX - driftX;
    world.y += newDriftY - driftY;
    driftX = newDriftX;
    driftY = newDriftY;
  }

  app.stage.eventMode = 'static';
  app.stage.hitArea = app.screen;
  app.stage.on('pointerdown', onPointerDown);
  app.stage.on('pointermove', onPointerMove);
  app.stage.on('pointerup', onPointerUp);
  app.stage.on('pointerupoutside', onPointerUp);
  app.canvas.addEventListener('wheel', onWheel, { passive: false });
  app.ticker.add(onTick);

  reset();

  function destroy(): void {
    app.stage.off('pointerdown', onPointerDown);
    app.stage.off('pointermove', onPointerMove);
    app.stage.off('pointerup', onPointerUp);
    app.stage.off('pointerupoutside', onPointerUp);
    app.canvas.removeEventListener('wheel', onWheel);
    app.ticker.remove(onTick);
  }

  return { destroy, reset, focusOn, getZoom };
}
