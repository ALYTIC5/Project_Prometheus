'use client';

import { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { fetchBuildings, fetchScoreboard, fetchWorldState } from '../api';
import { gridToScreen, TILE_HEIGHT, TILE_WIDTH } from '../iso/projection';
import { resolveSprite, type ConstructionPhase } from '../sprites/registry';
import type { Building, ScoreboardResponse, WorldState } from '../types';

const CANVAS_BG = 0x0a0a1a;
const GROUND_COLOR = 0x14241a;
const MONUMENT_BASE_HEIGHT = 90;

function hexToNumber(hex: string): number {
  return parseInt(hex.replace('#', ''), 16);
}

/** Draws one building as a flat-topped isometric prism: a diamond roof
 * plus two shaded side faces, sized by its grid footprint and coloured
 * by its real backend-reported color and construction_phase. Monument
 * gets a tall pillar instead, height driven by the real benchmark value
 * — the one deliberate exception to "every building is the same shape",
 * because PROMPTS.md asks for it explicitly.
 */
function drawBuilding(b: Building, benchmarkEquity: number, onSelect: (b: Building) => void): PIXI.Container {
  const container = new PIXI.Container();
  const { x: sx, y: sy } = gridToScreen(b.location.x + b.location.width / 2, b.location.y + b.location.height / 2);
  container.x = sx;
  container.y = sy;

  const spec = resolveSprite(
    b.kind === 'monument' ? 'monument' : 'building',
    b.kind,
    b.phase.toUpperCase() as ConstructionPhase,
  );

  const w = b.location.width * TILE_WIDTH * 0.9;
  const isMonument = b.kind === 'monument';
  const h = isMonument
    ? MONUMENT_BASE_HEIGHT * Math.max(0.2, benchmarkEquity / 1000)
    : b.location.height * TILE_HEIGHT * 1.8 + 20;

  const baseColor = hexToNumber(b.color);
  const g = new PIXI.Graphics();

  // Roof (top diamond)
  const halfW = w / 2;
  const halfH = TILE_HEIGHT * (b.location.height * 0.5 + 0.4);
  g.poly([0, -h - halfH, halfW, -h, 0, -h + halfH, -halfW, -h])
    .fill({ color: baseColor, alpha: spec.fillAlpha });

  // Left face
  g.poly([-halfW, -h, 0, -h + halfH, 0, halfH, -halfW, 0])
    .fill({ color: baseColor, alpha: spec.fillAlpha * 0.7 });

  // Right face
  g.poly([halfW, -h, 0, -h + halfH, 0, halfH, halfW, 0])
    .fill({ color: baseColor, alpha: spec.fillAlpha * 0.55 });

  // Phase decoration
  if (spec.outline === 'scaffold-lines') {
    g.moveTo(-halfW, -h * 0.3).lineTo(halfW, -h * 0.3).stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.8 });
    g.moveTo(-halfW, -h * 0.65).lineTo(halfW, -h * 0.65).stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.8 });
  } else if (spec.outline === 'chains') {
    g.rect(-halfW - 2, -h - halfH - 2, w + 4, h + halfH + 4).stroke({ color: spec.outlineColor, width: 2 });
  } else if (spec.outline === 'glow') {
    g.poly([0, -h - halfH - 3, halfW + 3, -h, 0, -h + halfH + 3, -halfW - 3, -h])
      .stroke({ color: spec.outlineColor, width: 1.5, alpha: 0.9 });
  }

  container.addChild(g);

  // Label
  const label = new PIXI.Text({
    text: isMonument ? `€${Math.round(benchmarkEquity)}` : b.id,
    style: { fill: 0xeeeeee, fontSize: 11, fontFamily: 'monospace' },
  });
  label.anchor.set(0.5, 1);
  label.y = -h - halfH - 8;
  container.addChild(label);

  container.eventMode = 'static';
  container.cursor = 'pointer';
  container.on('pointerdown', () => onSelect(b));

  // Depth sort key: further-back buildings (smaller grid y+x) draw first.
  (container as PIXI.Container & { __depth: number }).__depth = b.location.x + b.location.y;

  return container;
}

export default function WorldView() {
  const hostRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [scoreboard, setScoreboard] = useState<ScoreboardResponse | null>(null);
  const [world, setWorld] = useState<WorldState | null>(null);
  const [selected, setSelected] = useState<Building | null>(null);
  const [mode, setMode] = useState<'world' | 'truth'>('world');
  const [loading, setLoading] = useState(true);
  const [pixiReady, setPixiReady] = useState(false);
  const [pixiError, setPixiError] = useState<string | null>(null);

  // Poll the real backend — the world only ever shows what these calls return.
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
      .then(() => {
        if (destroyed || !hostRef.current) {
          app.destroy(true, { children: true });
          return;
        }
        hostRef.current.appendChild(app.canvas);
        appRef.current = app;
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

  // Redraw whenever the data or app changes.
  useEffect(() => {
    const app = appRef.current;
    if (!pixiReady || !app || buildings.length === 0) return;

    app.stage.removeChildren();
    const worldContainer = new PIXI.Container();
    worldContainer.x = app.screen.width / 2;
    worldContainer.y = app.screen.height / 2 - 60;
    app.stage.addChild(worldContainer);

    const ground = new PIXI.Graphics();
    ground.rect(-520, -300, 1040, 620).fill({ color: GROUND_COLOR, alpha: 0.6 });
    worldContainer.addChild(ground);

    const benchmarkEquity = scoreboard?.benchmark?.equity ?? 1000;
    const sorted = [...buildings].sort(
      (a, b) => a.location.x + a.location.y - (b.location.x + b.location.y),
    );
    for (const b of sorted) {
      worldContainer.addChild(drawBuilding(b, benchmarkEquity, setSelected));
    }
  }, [buildings, scoreboard, pixiReady]);

  if (!loading && mode === 'truth') {
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
      </div>

      <button
        onClick={() => setMode('truth')}
        style={{
          position: 'absolute', top: 10, right: 10, padding: 10, cursor: 'pointer',
          background: '#4A90D9', color: '#fff', border: 'none', borderRadius: 4,
        }}
      >
        Truth View →
      </button>

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
        </div>
      )}
    </div>
  );
}
