import * as PIXI from 'pixi.js';
import { gridToScreen } from '../iso/projection';
import { GRID_SIZE } from './ground';

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const DEFAULT_ZOOM = 1;

// Generous screen-space bounding box for the 26x26 iso grid, used to clamp
// panning so the city can't be dragged off screen entirely.
const GRID_HALF_WIDTH = (GRID_SIZE * 64) / 2 + 200;
const GRID_HALF_HEIGHT = (GRID_SIZE * 32) / 2 + 200;

export interface CameraHandle {
  /** Detaches all listeners. Call on unmount. */
  destroy: () => void;
  reset: () => void;
  focusOn: (gridX: number, gridY: number) => void;
}

/** A camera is a single transform (x, y, scale) applied to `world` before
 * drawing, per the camera-pan-zoom-controls pattern: drag pans, wheel
 * zooms toward the cursor (not the screen centre), and the result is
 * clamped to map bounds and snapped to whole pixels so pixel art doesn't
 * shimmer. Picking (render/selection.ts) inverts this exact transform via
 * Pixi's own Container.toLocal(), so there is only one transform to keep
 * in sync. */
export function attachCamera(app: PIXI.Application, world: PIXI.Container): CameraHandle {
  let scale = DEFAULT_ZOOM;
  let dragging = false;
  let lastPointer = { x: 0, y: 0 };

  function clamp(): void {
    scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale));
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
    scale = DEFAULT_ZOOM;
    world.x = app.screen.width / 2;
    world.y = app.screen.height / 2 - 60;
    clamp();
  }

  function focusOn(gridX: number, gridY: number): void {
    const { x, y } = gridToScreen(gridX, gridY);
    world.x = app.screen.width / 2 - x * scale;
    world.y = app.screen.height / 2 - y * scale;
    clamp();
  }

  function onPointerDown(e: PIXI.FederatedPointerEvent): void {
    dragging = true;
    lastPointer = { x: e.global.x, y: e.global.y };
  }

  function onPointerMove(e: PIXI.FederatedPointerEvent): void {
    if (!dragging) return;
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
    const rect = app.canvas.getBoundingClientRect();
    const cursorX = e.clientX - rect.left;
    const cursorY = e.clientY - rect.top;
    // Zoom toward the cursor: keep the world point under it stationary.
    const worldXBefore = (cursorX - world.x) / scale;
    const worldYBefore = (cursorY - world.y) / scale;
    scale *= e.deltaY < 0 ? 1.1 : 0.9;
    scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale));
    world.x = cursorX - worldXBefore * scale;
    world.y = cursorY - worldYBefore * scale;
    clamp();
  }

  app.stage.eventMode = 'static';
  app.stage.hitArea = app.screen;
  app.stage.on('pointerdown', onPointerDown);
  app.stage.on('pointermove', onPointerMove);
  app.stage.on('pointerup', onPointerUp);
  app.stage.on('pointerupoutside', onPointerUp);
  app.canvas.addEventListener('wheel', onWheel, { passive: false });

  reset();

  function destroy(): void {
    app.stage.off('pointerdown', onPointerDown);
    app.stage.off('pointermove', onPointerMove);
    app.stage.off('pointerup', onPointerUp);
    app.stage.off('pointerupoutside', onPointerUp);
    app.canvas.removeEventListener('wheel', onWheel);
  }

  return { destroy, reset, focusOn };
}
