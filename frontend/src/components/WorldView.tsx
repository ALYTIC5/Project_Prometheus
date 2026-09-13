'use client';

import { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { fetchBuildings, fetchScoreboard, fetchWorldState } from '../api';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import { attachCamera, type CameraHandle } from '../render/camera';
import { drawBuilding } from '../render/building';
import { createBuilders, type BuildersHandle } from '../render/builders';
import { drawGround } from '../render/ground';
import { updateLabels, type LabelCandidate } from '../render/labels';
import { createMonument, type MonumentHandle } from '../render/monument';
import { drawHoverOutline, drawSelectionOutline, pickBuilding } from '../render/selection';
import { drawVignette } from '../render/vignette';
import { loadAtlasTextures } from '../sprites/atlasTextures';
import type { Building, ScoreboardResponse, WorldState } from '../types';

const CANVAS_BG = 0x0a0a1a;
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

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [scoreboard, setScoreboard] = useState<ScoreboardResponse | null>(null);
  const [world, setWorld] = useState<WorldState | null>(null);
  const [selected, setSelected] = useState<Building | null>(null);
  const [mode, setMode] = useState<'world' | 'truth'>('world');
  const [loading, setLoading] = useState(true);
  const [pixiReady, setPixiReady] = useState(false);
  const [pixiError, setPixiError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);

  useEffect(() => {
    buildingsStateRef.current = buildings;
  }, [buildings]);
  useEffect(() => {
    scoreboardStateRef.current = scoreboard;
  }, [scoreboard]);
  useEffect(() => {
    selectedIdRef.current = selected?.id ?? null;
  }, [selected]);

  // Poll the real backend -- the world only ever shows what these calls return.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [b, s, w] = await Promise.all([fetchBuildings(), fetchScoreboard(), fetchWorldState()]);
        if (cancelled) return;
        setBuildings(b.buildings ?? []);
        setScoreboard(s);
        setWorld(w);
      } catch (err) {
        console.error('world data fetch failed:', err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

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

        cameraRef.current = attachCamera(app, world);

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
          if (id) {
            const b = buildingsStateRef.current.find((x) => x.id === id);
            if (b) setSelected(b);
          } else {
            setSelected(null);
          }
        });

        let frames = 0;
        let fpsAccum = 0;
        app.ticker.add((ticker) => {
          const deltaMs = ticker.deltaMS;
          monumentRef.current?.update(scoreboardStateRef.current?.benchmark?.equity ?? 1000, deltaMs);
          buildersRef.current?.update(ticker.lastTime);
          redrawOverlays(ticker.lastTime);
          redrawLabels();
          buildingsLayer.sortChildren();

          frames++;
          fpsAccum += deltaMs;
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
    for (const b of nonMonument) {
      layer.addChild(drawBuilding(b));
    }
    // removeChildren() above also detached the monument (if it already
    // existed) -- Pixi's addChild re-parents an already-parented display
    // object rather than duplicating it, so this simply re-inserts it.
    if (monumentRef.current) layer.addChild(monumentRef.current.container);

    const handle = createBuilders(nonMonument);
    for (const root of handle.roots) layer.addChild(root);
    buildersRef.current = handle;
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
      <div ref={hostRef} style={{ width: '100%', height: '100%' }} />

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

      <div style={{ position: 'absolute', top: 10, left: 10, color: '#eee', fontFamily: 'monospace', pointerEvents: 'none' }}>
        <h1 style={{ margin: 0, fontSize: 22 }}>Project Prometheus</h1>
        {world && (
          <p style={{ margin: '4px 0' }}>
            Tick: {world.tick} · {new Date(world.generated_at).toLocaleTimeString()}
          </p>
        )}
        {scoreboard && (
          <p style={{ margin: '4px 0', color: '#F39C12' }}>
            Your system: {scoreboard.system_value !== null ? `€${scoreboard.system_value.toFixed(0)}` : '€—'}
            {' | '}Just holding: €{scoreboard.benchmark_value.toFixed(0)}
            {' | '}Verdict: {scoreboard.verdict}
          </p>
        )}
        {world && (
          <p style={{ margin: '4px 0', color: '#4A90D9' }}>
            Build Progress: {world.build_progress.active}/{world.build_progress.total} systems online
          </p>
        )}
        {pixiReady && <p style={{ margin: '4px 0', color: '#555' }}>{fps} fps · press D for depth overlay</p>}
      </div>

      <div style={{ position: 'absolute', top: 10, right: 10, display: 'flex', gap: 8 }}>
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

      {selected && (
        <div
          style={{
            position: 'absolute', bottom: 20, left: 20, background: 'rgba(0,0,0,0.85)',
            color: '#eee', padding: 16, borderRadius: 8, fontFamily: 'monospace', maxWidth: 420,
          }}
        >
          <button
            onClick={() => setSelected(null)}
            style={{ float: 'right', cursor: 'pointer', background: 'none', border: 'none', color: '#fff', fontSize: 16 }}
          >
            ×
          </button>
          <h3 style={{ margin: '0 0 8px', textTransform: 'capitalize' }}>{selected.id}</h3>
          <p style={{ margin: '4px 0', opacity: 0.8 }}>{selected.description}</p>
          {selected.phase !== 'active' && selected.prompt !== null && (
            <p style={{ margin: '8px 0 0', color: '#F39C12' }}>
              Under Construction — Built in Prompt {selected.prompt}
            </p>
          )}
          {selected.phase === 'active' && (
            <p style={{ margin: '8px 0 0', color: '#FFD700' }}>ACTIVE</p>
          )}
          {selected.phase === 'sealed' && (
            <p style={{ margin: '8px 0 0', color: '#ff5555' }}>SEALED — sacred, inaccessible by design</p>
          )}
          <button
            onClick={() => cameraRef.current?.focusOn(selected.location.x, selected.location.y)}
            style={{ marginTop: 10, padding: 6, cursor: 'pointer' }}
          >
            Focus camera
          </button>
        </div>
      )}
    </div>
  );
}
