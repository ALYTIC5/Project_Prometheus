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

// WORLD_CONSTITUTION.md's W4.2: eased transitions, ~600ms, never instant
// except under prefers-reduced-motion (an instant cut there instead).
const FOCUS_DURATION_MS = 600;

export interface CameraPosition {
  x: number;
  y: number;
  scale: number;
}

export interface CameraHandle {
  /** Detaches all listeners. Call on unmount. */
  destroy: () => void;
  reset: () => void;
  focusOn: (gridX: number, gridY: number) => void;
  getZoom: () => number;
  /** For a back-stack: capture the current transform before focusing away
   * from it, so Escape can animate back to exactly where the camera was. */
  getPosition: () => CameraPosition;
  restorePosition: (position: CameraPosition) => void;
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
export function attachCamera(
  app: PIXI.Application,
  world: PIXI.Container,
  reducedMotionRef: { current: boolean },
): CameraHandle {
  let defaultZoom = 1;
  let minZoom = 0.5;
  let maxZoom = 3;
  let scale = defaultZoom;
  let dragging = false;
  let lastPointer = { x: 0, y: 0 };

  // Eased focus/reset animation (W4.2). No idle drift: WORLD_CONSTITUTION.md
  // prohibits "constant camera motion" outright -- the prior idle-drift
  // sine wave violated that as soon as the constitution was adopted, so it
  // is removed here, not just gated behind reduced-motion.
  let animating = false;
  let animStart = 0;
  let animFrom: CameraPosition = { x: 0, y: 0, scale: 1 };
  let animTo: CameraPosition = { x: 0, y: 0, scale: 1 };

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

  /** A direct manipulation (drag, wheel) cancels any in-flight eased
   * animation -- the user's hands-on input always wins immediately. */
  function cancelAnimation(): void {
    animating = false;
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

  /** Starts (or, under reduced motion, instantly applies) an eased
   * transition to the given transform. The sole path every camera movement
   * that isn't direct drag/wheel manipulation goes through. */
  function animateTo(toX: number, toY: number, toScale: number): void {
    if (reducedMotionRef.current) {
      animating = false;
      world.x = toX;
      world.y = toY;
      scale = toScale;
      clamp();
      return;
    }
    animFrom = { x: world.x, y: world.y, scale };
    animTo = { x: toX, y: toY, scale: toScale };
    animStart = performance.now();
    animating = true;
  }

  function reset(): void {
    computeFit();
    animateTo(app.screen.width / 2, app.screen.height / 2 - 60, defaultZoom);
  }

  function focusOn(gridX: number, gridY: number): void {
    const { x, y } = gridToScreen(gridX, gridY);
    animateTo(app.screen.width / 2 - x * scale, app.screen.height / 2 - y * scale, scale);
  }

  function getZoom(): number {
    return scale;
  }

  function getPosition(): CameraPosition {
    return { x: world.x, y: world.y, scale };
  }

  function restorePosition(position: CameraPosition): void {
    animateTo(position.x, position.y, position.scale);
  }

  function onPointerDown(e: PIXI.FederatedPointerEvent): void {
    cancelAnimation();
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
    cancelAnimation();
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

  // Ease-out cubic -- fast start, settles gently, ~600ms (W4.2). Runs only
  // while an eased transition is in flight; idle time is genuinely idle
  // (no drift -- WORLD_CONSTITUTION.md prohibits constant camera motion).
  function onTick(): void {
    if (!animating) return;
    const t = Math.min(1, (performance.now() - animStart) / FOCUS_DURATION_MS);
    const eased = 1 - (1 - t) ** 3;
    world.x = animFrom.x + (animTo.x - animFrom.x) * eased;
    world.y = animFrom.y + (animTo.y - animFrom.y) * eased;
    scale = animFrom.scale + (animTo.scale - animFrom.scale) * eased;
    clamp();
    if (t >= 1) animating = false;
  }

  app.stage.eventMode = 'static';
  app.stage.hitArea = app.screen;
  app.stage.on('pointerdown', onPointerDown);
  app.stage.on('pointermove', onPointerMove);
  app.stage.on('pointerup', onPointerUp);
  app.stage.on('pointerupoutside', onPointerUp);
  app.canvas.addEventListener('wheel', onWheel, { passive: false });
  app.ticker.add(onTick);

  // Initial placement snaps instantly -- the city should simply be there on
  // load, not fly in from the origin corner. Only user-triggered resets
  // (the "Reset View" button) ease, like every other camera movement.
  computeFit();
  world.x = app.screen.width / 2;
  world.y = app.screen.height / 2 - 60;
  scale = defaultZoom;
  clamp();

  function destroy(): void {
    app.stage.off('pointerdown', onPointerDown);
    app.stage.off('pointermove', onPointerMove);
    app.stage.off('pointerup', onPointerUp);
    app.stage.off('pointerupoutside', onPointerUp);
    app.canvas.removeEventListener('wheel', onWheel);
    app.ticker.remove(onTick);
  }

  return { destroy, reset, focusOn, getZoom, getPosition, restorePosition };
}
