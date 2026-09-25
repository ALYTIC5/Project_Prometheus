'use client';

import { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { useBuildingsQuery, useScoreboardQuery, useWorldStateQuery } from '../data/queries';
import { usePrefersReducedMotion } from '../hooks/usePrefersReducedMotion';
import { Layer, depthOf, gridToScreen } from './iso/projection';
import { attachCamera, type CameraHandle, type CameraPosition } from './render/camera';
import { drawBuilding } from './render/building';
import { createBuilders, type BuildersHandle } from './render/builders';
import { createGods } from './render/gods';
import { drawGround } from './render/ground';
import { createVegetation } from './render/vegetation';
import { createDecor } from './render/decor';
import { updateLabels, type LabelCandidate } from './render/labels';
import { createMonument, type MonumentHandle } from './render/monument';
import { drawHoverOutline, drawSelectionOutline, pickBuilding } from './render/selection';
import { drawVignette } from './render/vignette';
import { loadAtlasTextures } from './sprites/atlasTextures';
import { BenchmarkStrip } from '../components/BenchmarkStrip';
import { SearchPalette } from '../components/SearchPalette';
import { TruthDrawer } from '../components/TruthDrawer';
import type { Building, ScoreboardResponse } from '../types';

// A dusk-sky tone, not near-black: at 26% frame occupancy (city fills a
// small fraction of the viewport pre-Prompt-3 map-resize/fit-to-bounds),
// empty background otherwise caps any brightness measurement regardless of
// how bright the city itself is. Still much darker than the city so it
// doesn't compete with it.
const CANVAS_BG = 0x1c2438;
const ZOOM_LABEL_THRESHOLD = 1.5;

export default function WorldView() {
  const hostRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const cameraRef = useRef<CameraHandle | null>(null);
  const monumentRef = useRef<MonumentHandle | null>(null);
  const buildersRef = useRef<BuildersHandle | null>(null);
  const buildingsLayerRef = useRef<PIXI.Container | null>(null);
  const groundLayerRef = useRef<PIXI.Container | null>(null);
  const labelLayerRef = useRef<PIXI.Container | null>(null);
  const overlayLayerRef = useRef<PIXI.Container | null>(null);
  const debugLayerRef = useRef<PIXI.Container | null>(null);

  const buildingsStateRef = useRef<Building[]>([]);
  const scoreboardStateRef = useRef<ScoreboardResponse | null>(null);
  const hoveredRef = useRef<string | null>(null);
  const selectedIdRef = useRef<string | null>(null);
  const debugRef = useRef(false);
  // The ticker callback below is registered once on mount (empty-deps
  // effect) -- a ref, not the reducedMotion state value directly, is what
  // lets it see later prefers-reduced-motion changes.
  const reducedMotionRef = useRef(false);
  // W4.2's back-stack: the camera position captured just before each
  // focus-away, so Escape can animate back to exactly where it was.
  const cameraHistoryRef = useRef<CameraPosition[]>([]);
  const buildingContainersRef = useRef(new Map<string, PIXI.Container>());

  // Server state via TanStack Query (WORLD_CONSTITUTION.md's W0.3) -- the
  // one data adapter module is src/data/queries.ts; nothing here calls
  // fetch/../api directly. The world only ever shows what these return.
  const buildingsQuery = useBuildingsQuery();
  const scoreboardQuery = useScoreboardQuery();
  const worldQuery = useWorldStateQuery();

  const buildings = buildingsQuery.data?.buildings ?? [];
  const scoreboard = scoreboardQuery.data ?? null;
  const world = worldQuery.data ?? null;
  const entities = world?.entities ?? [];
  const loading = buildingsQuery.isLoading || scoreboardQuery.isLoading || worldQuery.isLoading;
  const reducedMotion = usePrefersReducedMotion();

  // A WorldEntity id ("building:library", "god:archive_keeper", ...), not a
  // plain Building -- the truth drawer and search palette operate on any
  // real entity, not just buildings the canvas picking can hit.
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [mode, setMode] = useState<'world' | 'truth'>('world');
  const [pixiReady, setPixiReady] = useState(false);
  const [pixiError, setPixiError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);
  const [liveMessage, setLiveMessage] = useState('');

  useEffect(() => {
    buildingsStateRef.current = buildings;
  }, [buildings]);
  useEffect(() => {
    scoreboardStateRef.current = scoreboard;
  }, [scoreboard]);
  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
  }, [reducedMotion]);
  useEffect(() => {
    // The canvas selection outline/labels only understand a plain building
    // id -- a GOD (or any future non-building) selection simply has no
    // canvas outline, which is correct: gods have no footprint of their own.
    const buildingId = selectedEntityId?.startsWith('building:') ? selectedEntityId.slice('building:'.length) : null;
    selectedIdRef.current = buildingId;
  }, [selectedEntityId]);

  // W1.4 accessibility: a visually-hidden live region announcing real world
  // events in text, alongside the canvas's aria-label -- the canvas is an
  // enhancement, never the only way to know something happened.
  useEffect(() => {
    const latest = world?.events?.[0];
    if (latest) setLiveMessage(`${latest.type}: ${latest.subject_id}${latest.message ? ` -- ${latest.message}` : ''}`);
  }, [world?.events]);

  // Set up the PixiJS application once.
  useEffect(() => {
    if (!hostRef.current || appRef.current) return;
    let destroyed = false;
    const app = new PIXI.Application();
    void app
      .init({ background: CANVAS_BG, resizeTo: window, antialias: true })
      .then(() => loadAtlasTextures())
      .then(() => {
        if (destroyed || !hostRef.current) {
          app.destroy(true, { children: true });
          return;
        }
        hostRef.current.appendChild(app.canvas);
        appRef.current = app;

        // `world` is a FIXED-ORDER layer stack (ground always behind
        // everything, overlay/labels/debug always in front) -- it must
        // NOT be sortableChildren itself. Only `buildingsLayer` (the
        // "entities" layer: buildings, the monument, and builders all as
        // siblings) is depth-sorted, so an object of any of those three
        // kinds can correctly occlude or be occluded by any other,
        // regardless of which one added it. Splitting them into separate
        // sibling containers of `world` (an earlier version of this file
        // did exactly that for the monument and builders) breaks
        // cross-type occlusion entirely, since containers only stack by
        // insertion order relative to each other, not by zIndex.
        const world = new PIXI.Container();
        app.stage.addChild(world);
        // Ground needs real building locations (for the plaza + road
        // network), which haven't loaded yet at Pixi-init time -- this
        // starts empty and is populated by the buildings-redraw effect
        // below, once real data exists.
        const groundLayer = new PIXI.Container();
        const buildingsLayer = new PIXI.Container();
        buildingsLayer.sortableChildren = true;
        const labelLayer = new PIXI.Container();
        const overlayLayer = new PIXI.Container();
        const debugLayer = new PIXI.Container();
        world.addChild(groundLayer);
        world.addChild(buildingsLayer);
        world.addChild(overlayLayer);
        world.addChild(labelLayer);
        world.addChild(debugLayer);
        groundLayerRef.current = groundLayer;
        buildingsLayerRef.current = buildingsLayer;
        labelLayerRef.current = labelLayer;
        overlayLayerRef.current = overlayLayer;
        debugLayerRef.current = debugLayer;

        cameraRef.current = attachCamera(app, world, reducedMotionRef);

        // Screen-space vignette -- added to app.stage, not `world`, so it
        // stays fixed relative to the viewport instead of panning/zooming
        // with the camera. Redrawn on resize (app.screen changes as the
        // window does, since Pixi was init'd with resizeTo: window).
        let vignette = drawVignette(app.screen.width, app.screen.height);
        app.stage.addChild(vignette);
        app.renderer.on('resize', (w: number, h: number) => {
          app.stage.removeChild(vignette);
          vignette = drawVignette(w, h);
          app.stage.addChild(vignette);
        });

        app.stage.on('pointermove', (e: PIXI.FederatedPointerEvent) => {
          const id = pickBuilding(e.global, world, buildingsStateRef.current);
          hoveredRef.current = id;
        });
        app.stage.on('pointertap', (e: PIXI.FederatedPointerEvent) => {
          const id = pickBuilding(e.global, world, buildingsStateRef.current);
          // W4.1 "click temple: camera eases closer" -- clicking a building
          // both opens the drawer and focuses the camera, same as search
          // (W1.3's "both, always" rule). W4.2's back-stack: capture where
          // the camera was before moving, so Escape can return to it.
          if (id) {
            const b = buildingsStateRef.current.find((x) => x.id === id);
            if (b && cameraRef.current) {
              cameraHistoryRef.current.push(cameraRef.current.getPosition());
              cameraRef.current.focusOn(b.location.x, b.location.y);
            }
          }
          setSelectedEntityId(id ? `building:${id}` : null);
        });

        // Hover brighten (~10%), W4.3 -- a ColorMatrixFilter, not a tint
        // (tint can only darken toward a colour; brightening a mix of real
        // atlas sprites and procedural Graphics needs a real filter). One
        // shared instance, reused every frame rather than allocated per-tick.
        const hoverBrighten = new PIXI.ColorMatrixFilter();
        hoverBrighten.brightness(1.1, false);

        let frames = 0;
        let fpsAccum = 0;
        app.ticker.add((ticker) => {
          // W1.4: prefers-reduced-motion freezes idle/pulse animation at a
          // constant frame instead of animating -- both builders.ts's bob
          // and selection.ts's pulse are pure functions of elapsed time, so
          // feeding a constant is sufficient; no changes needed inside them.
          const reduced = reducedMotionRef.current;
          const deltaMs = reduced ? 0 : ticker.deltaMS;
          const elapsed = reduced ? 0 : ticker.lastTime;
          monumentRef.current?.update(scoreboardStateRef.current?.benchmark?.equity ?? 1000, deltaMs);
          buildersRef.current?.update(elapsed);
          redrawOverlays(elapsed);
          redrawLabels();
          buildingsLayer.sortChildren();

          const hoveredId = hoveredRef.current;
          buildingContainersRef.current.forEach((container, bid) => {
            container.filters = bid === hoveredId ? [hoverBrighten] : [];
          });

          // FPS is a diagnostic, not decorative animation -- always the real
          // delta, unaffected by prefers-reduced-motion.
          frames++;
          fpsAccum += ticker.deltaMS;
          if (fpsAccum >= 1000) {
            setFps(Math.round((frames * 1000) / fpsAccum));
            frames = 0;
            fpsAccum = 0;
          }
        });

        setPixiReady(true);
      })
      .catch((err: unknown) => {
        console.error('PixiJS init failed:', err);
        setPixiError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      destroyed = true;
      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
        appRef.current = null;
      }
    };
  }, []);

  function redrawOverlays(nowMs: number): void {
    const overlay = overlayLayerRef.current;
    if (!overlay) return;
    overlay.removeChildren();
    const hoveredId = hoveredRef.current;
    const selectedId = selectedIdRef.current;
    const list = buildingsStateRef.current;
    if (hoveredId && hoveredId !== selectedId) {
      const b = list.find((x) => x.id === hoveredId);
      if (b) overlay.addChild(drawHoverOutline(b.location));
    }
    if (selectedId) {
      const b = list.find((x) => x.id === selectedId);
      if (b) overlay.addChild(drawSelectionOutline(b.location, nowMs));
    }
  }

  // Zoom changes continuously via drag/wheel (camera state, not React
  // state), so labels are recomputed every frame like the hover/selection
  // overlays above, not only when buildings/selection change.
  function redrawLabels(): void {
    const layer = labelLayerRef.current;
    if (!layer) return;
    const zoom = cameraRef.current?.getZoom() ?? 1;
    const candidates: LabelCandidate[] = buildingsStateRef.current.map((b) => {
      const anchor = gridToScreen(b.location.x + b.location.width / 2, b.location.y);
      return {
        id: b.id,
        x: anchor.x,
        y: anchor.y - 60,
        text: b.id,
        force: b.id === hoveredRef.current || b.id === selectedIdRef.current,
      };
    });
    updateLabels(layer, candidates, zoom > ZOOM_LABEL_THRESHOLD);
  }

  // Create the monument once buildings/pixi are ready (its geometry is a
  // special case per render/monument.ts, but it still lives in the shared
  // sortable entities layer for correct occlusion -- see below).
  useEffect(() => {
    const layer = buildingsLayerRef.current;
    if (!pixiReady || !layer || buildings.length === 0 || monumentRef.current) return;
    const monument = buildings.find((b) => b.kind === 'monument');
    if (!monument) return;
    const handle = createMonument(
      monument.location.x,
      monument.location.y,
      scoreboard?.benchmark?.equity ?? 1000,
    );
    // Added to buildingsLayer (the shared sortable "entities" layer), NOT
    // `world` directly -- it must compete on zIndex with every other
    // building and builder for correct occlusion, the same reason
    // builders live there too (see the effect below).
    buildingsLayerRef.current?.addChild(handle.container);
    monumentRef.current = handle;
  }, [pixiReady, buildings, scoreboard]);

  // Redraw non-monument buildings and builders whenever real data changes.
  // All three (buildings, the monument, builders) share this one
  // sortableChildren layer so any of them can correctly occlude any other
  // by real zIndex -- separate sibling containers can only stack by
  // insertion order relative to each other, which is the layering bug
  // this replaced (ground was drawing over every building for exactly
  // this reason).
  useEffect(() => {
    const layer = buildingsLayerRef.current;
    const groundLayer = groundLayerRef.current;
    if (!pixiReady || !layer || buildings.length === 0) return;

    if (groundLayer) {
      groundLayer.removeChildren();
      groundLayer.addChild(drawGround(buildings));
    }

    layer.removeChildren();
    const nonMonument = buildings.filter((b) => b.kind !== 'monument');
    buildingContainersRef.current.clear();
    for (const b of nonMonument) {
      const container = drawBuilding(b);
      layer.addChild(container);
      // Keyed for the ticker's hover-brighten filter (W4.3) -- a plain
      // per-building lookup, not re-derived from the display tree.
      buildingContainersRef.current.set(b.id, container);
    }
    // removeChildren() above also detached the monument (if it already
    // existed) -- Pixi's addChild re-parents an already-parented display
    // object rather than duplicating it, so this simply re-inserts it.
    if (monumentRef.current) layer.addChild(monumentRef.current.container);

    const handle = createBuilders(nonMonument);
    for (const root of handle.roots) layer.addChild(root);
    buildersRef.current = handle;

    // Gods stand at their real building (archive/oracle/vault) -- static,
    // no per-frame update, recomputed fresh on every redraw like builders.
    for (const root of createGods(nonMonument)) layer.addChild(root);

    // Vegetation is static geography, not agent/building state -- still
    // lives in the shared sortable layer (Layer.PROP) so it occludes and is
    // occluded correctly against buildings and agents at the same tile.
    for (const root of createVegetation(nonMonument)) layer.addChild(root);

    // Static decor (amphorae, a fallen column, a brazier, a bench, a herm)
    // -- same layer/occlusion treatment as vegetation; a no-op in
    // placeholder mode (see decor.ts's DECOR_NAMES docstring).
    for (const root of createDecor(nonMonument)) layer.addChild(root);
  }, [pixiReady, buildings]);

  // Debug overlay (press D): per-object grid coords + depth value.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key.toLowerCase() !== 'd') return;
      debugRef.current = !debugRef.current;
      const layer = debugLayerRef.current;
      if (!layer) return;
      layer.removeChildren();
      if (!debugRef.current) return;
      for (const b of buildingsStateRef.current) {
        const { x, y, width, height } = b.location;
        const depth = depthOf(x, y, width, height, Layer.BUILDING);
        const anchor = gridToScreen(x + width / 2, y + height / 2);
        const text = new PIXI.Text({
          text: `${b.id}\n(${x},${y}) d=${depth}`,
          style: { fill: 0x66ff66, fontSize: 9, fontFamily: 'monospace', align: 'center' },
        });
        text.anchor.set(0.5, 0.5);
        text.x = anchor.x;
        text.y = anchor.y;
        layer.addChild(text);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  if (mode === 'truth') {
    return (
      <div style={{ color: '#eee', padding: 40, fontFamily: 'monospace', background: '#0a0a1a', minHeight: '100vh' }}>
        <h1 style={{ color: '#4A90D9' }}>Truth View</h1>
        {scoreboard && (
          <div style={{ marginTop: 20 }}>
            <p>System: {scoreboard.system_value !== null ? scoreboard.system_value.toFixed(2) : '—'} {scoreboard.currency}</p>
            <p>Benchmark: {scoreboard.benchmark_value.toFixed(2)} {scoreboard.currency}</p>
            <p>Excess: {scoreboard.excess !== null ? scoreboard.excess.toFixed(2) : '—'} {scoreboard.currency}</p>
            <p>Verdict: {scoreboard.verdict_label}</p>
          </div>
        )}
        <div style={{ marginTop: 20 }}>
          <h2 style={{ color: '#8E44AD' }}>Laws</h2>
          {world?.laws.map((law) => (
            <div key={law.law_id} style={{ padding: '4px 0' }}>
              Law {law.law_id} — {law.name}: {law.compliant ? '✓ compliant' : '✗ VIOLATION'}
            </div>
          ))}
        </div>
        {world?.events && world.events.length > 0 && (
          <div style={{ marginTop: 20 }}>
            <h2 style={{ color: '#E74C3C' }}>Recent Events</h2>
            {world.events.map((e, i) => (
              <div key={i} style={{ padding: 4, borderBottom: '1px solid #222' }}>
                {e.type}: {e.subject_id} ({e.severity}) {e.message ?? ''}
              </div>
            ))}
          </div>
        )}
        <button onClick={() => setMode('world')} style={{ marginTop: 20, padding: 10, cursor: 'pointer' }}>
          ← Back to World View
        </button>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', background: '#0a0a1a' }}>
      <BenchmarkStrip scoreboard={scoreboard} />
      <SearchPalette
        entities={entities}
        onSelect={(entity) => {
          setSelectedEntityId(entity.entity_id);
          if (cameraRef.current) {
            cameraHistoryRef.current.push(cameraRef.current.getPosition());
            cameraRef.current.focusOn(entity.location.x, entity.location.y);
          }
        }}
      />
      <TruthDrawer
        entityId={selectedEntityId}
        entities={entities}
        buildings={buildings}
        onOpenChange={(open) => {
          if (open) return;
          setSelectedEntityId(null);
          // W4.1/W4.2: "Escape ... camera returns to prior level" -- animate
          // back to wherever the camera was before this focus, if anywhere.
          const previous = cameraHistoryRef.current.pop();
          if (previous) cameraRef.current?.restorePosition(previous);
        }}
        onFocus={(x, y) => {
          if (cameraRef.current) {
            cameraHistoryRef.current.push(cameraRef.current.getPosition());
            cameraRef.current.focusOn(x, y);
          }
        }}
      />

      {/* W1.4: the canvas is an enhancement, never the only path to any
          action -- an aria-label names what it shows, and this visually-
          hidden live region announces real world events in text for anyone
          not looking at (or not able to see) the canvas. */}
      <div ref={hostRef} style={{ width: '100%', height: '100%' }} role="img" aria-label="Isometric view of Project Prometheus's research pipeline" />
      <div aria-live="polite" className="sr-only">
        {liveMessage}
      </div>

      {loading && (
        <div style={{ color: '#aaa', padding: 40, fontFamily: 'monospace', position: 'absolute', top: 0, left: 0 }}>
          Loading world...
        </div>
      )}

      {pixiError && (
        <div
          style={{
            position: 'absolute', bottom: 10, left: 10, right: 10, background: 'rgba(120,0,0,0.85)',
            color: '#fff', padding: 12, borderRadius: 6, fontFamily: 'monospace', fontSize: 12,
          }}
        >
          Pixel-art renderer failed to start ({pixiError}). This browser/GPU may not support
          WebGL — the world data above is still real, just rendered as text.
        </div>
      )}

      <div style={{ position: 'absolute', top: 44, left: 10, color: '#eee', fontFamily: 'monospace', pointerEvents: 'none' }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Project Prometheus</h1>
        {world && (
          <p style={{ margin: '4px 0' }}>
            Tick: {world.tick} · {new Date(world.generated_at).toLocaleTimeString()}
          </p>
        )}
        {world && (
          <p style={{ margin: '4px 0', color: '#4A90D9' }}>
            Build Progress: {world.build_progress.active}/{world.build_progress.total} systems online
          </p>
        )}
        {pixiReady && (
          <p style={{ margin: '4px 0', color: '#555' }}>
            {fps} fps · press D for depth overlay · Ctrl/Cmd-K to search
          </p>
        )}
      </div>

      <div style={{ position: 'absolute', top: 44, right: 10, display: 'flex', gap: 8 }}>
        <button
          onClick={() => cameraRef.current?.reset()}
          style={{ padding: 10, cursor: 'pointer', background: '#333', color: '#fff', border: 'none', borderRadius: 4 }}
        >
          Reset View
        </button>
        <button
          onClick={() => setMode('truth')}
          style={{ padding: 10, cursor: 'pointer', background: '#4A90D9', color: '#fff', border: 'none', borderRadius: 4 }}
        >
          Truth View →
        </button>
      </div>
    </div>
  );
}
