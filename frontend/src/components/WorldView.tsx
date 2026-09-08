'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Container, Graphics, Sprite } from '@pixi/react';
import { fetchWorldState, fetchBuildings, fetchScoreboard } from './api';
import type { WorldState, Structure, District } from './types';

const BUILDING_COLORS: Record<string, string> = {
  library: '#4A90D9',
  forge: '#E67E22',
  oracle: '#8E44AD',
  arena: '#F1C40F',
  vault: '#7F8C8D',
  treasury: '#27AE60',
  harbour: '#3498DB',
  archive: '#95A5A6',
  underworld: '#2C3E50',
  watchtower: '#E74C3C',
  temple: '#D4A574',
  monument: '#F39C12',
};

function isoProject(x: number, y: number, z: number): [number, number] {
  const isoX = (x - y) * 32;
  const isoY = ((x + y) * 16) - z * 30;
  return [isoX, isoY];
}

function drawBuilding(
  g: Graphics,
  x: number,
  y: number,
  z: number,
  color: string,
  width: number,
  height: number,
  phase: string,
) {
  const [sx, sy] = isoProject(x, y, z);
  const w = width * 20;
  const h = height * 20;

  g.beginFill(phase === 'active' ? color : '#555555');
  g.lineStyle(1, 0x333333);
  g.drawRoundedRect(sx - w / 2, sy - h, w, h, 4);
  g.endFill();

  if (phase === 'scaffolding') {
    g.lineStyle(2, 0xAAAAAA);
    g.moveTo(sx - w / 2 + 4, sy - h + 4);
    g.lineTo(sx + w / 2 - 4, sy - h + 4);
    g.moveTo(sx - w / 2 + 4, sy - h / 2);
    g.lineTo(sx + w / 2 - 4, sy - h / 2);
    g.moveTo(sx - w / 2 + 4, sy - 4);
    g.lineTo(sx + w / 2 - 4, sy - 4);
  }

  if (phase === 'sealed') {
    g.lineStyle(2, 0xFF0000);
    g.drawRoundedRect(sx - w / 2 - 2, sy - h - 2, w + 4, h + 4, 6);
  }

  if (phase === 'active') {
    g.lineStyle(1, 0xFFD700);
    g.drawRoundedRect(sx - w / 2 - 1, sy - h - 1, w + 2, h + 2, 6);
  }
}

export default function WorldView() {
  const appRef = useRef<PIXI.Application | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [world, setWorld] = useState<WorldState | null>(null);
  const [selectedBuilding, setSelectedBuilding] = useState<string | null>(null);
  const [buildings, setBuildings] = useState<any[]>([]);
  const [scoreboard, setScoreboard] = useState<any>(null);
  const [mode, setMode] = useState<'world' | 'truth'>('world');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [w, b, s] = await Promise.all([
          fetchWorldState().catch(() => null),
          fetchBuildings().catch(() => []),
          fetchScoreboard().catch(() => null),
        ]);
        setWorld(w);
        setBuildings(Array.isArray(b) ? b : (b.buildings || []));
        setScoreboard(s);
      } catch {
        // API unavailable — show empty world
      }
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!canvasRef.current) return;
    if (appRef.current) return;

    const app = new PIXI.Application({
      view: canvasRef.current,
      width: window.innerWidth,
      height: window.innerHeight,
      backgroundColor: 0x1a1a2e,
      antialias: true,
      autoDensity: true,
    });
    appRef.current = app;

    return () => {
      app.destroy(true);
      appRef.current = null;
    };
  }, []);

  if (loading) {
    return (
      <div style={{ color: '#aaa', padding: 40, fontFamily: 'monospace' }}>
        Loading world...
      </div>
    );
  }

  if (mode === 'truth') {
    return (
      <div style={{ color: '#eee', padding: 40, fontFamily: 'monospace', background: '#0a0a1a' }}>
        <h1 style={{ color: '#4A90D9' }}>Truth View</h1>
        {scoreboard && (
          <div style={{ marginTop: 20 }}>
            <p>System: {scoreboard.system_value?.toFixed(2) || '—'} {scoreboard.currency}</p>
            <p>Benchmark: {scoreboard.benchmark_value.toFixed(2)} {scoreboard.currency}</p>
            <p>Excess: {scoreboard.excess?.toFixed(2) || '—'} {scoreboard.currency}</p>
            <p>Verdict: {scoreboard.verdict}</p>
          </div>
        )}
        {world?.events && world.events.length > 0 && (
          <div style={{ marginTop: 20 }}>
            <h2 style={{ color: '#E74C3C' }}>Recent Events</h2>
            {world.events.map((e, i) => (
              <div key={i} style={{ padding: 4, borderBottom: '1px solid #222' }}>
                {e.type}: {e.subject_id} ({e.severity}) {e.message || ''}
              </div>
            ))}
          </div>
        )}
        <button
          onClick={() => setMode('world')}
          style={{ marginTop: 20, padding: 10, cursor: 'pointer' }}
        >
          ← Back to World View
        </button>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100vh', background: '#0a0a1a' }}>
      <canvas ref={canvasRef} style={{ width: '100%', height: '100%' }} />

      <div style={{ position: 'absolute', top: 10, left: 10, color: '#eee', fontFamily: 'monospace' }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Project Prometheus</h1>
        {world && (
          <p>Tick: {world.tick} | Generated: {new Date(world.generated_at).toLocaleTimeString()}</p>
        )}
        <div style={{ marginTop: 8, color: '#F39C12' }}>
          {scoreboard && (
            <>
              System: {scoreboard.system_value?.toFixed(2) || '—'} | Just Holding: {scoreboard.benchmark_value.toFixed(2)} | Verdict: {scoreboard.verdict}
            </>
          )}
        </div>
        <div style={{ marginTop: 4, color: '#4A90D9' }}>
          Build Progress: {world?.build_progress.active || 0}/{world?.build_progress.total || 12} systems online
        </div>
      </div>

      <button
        onClick={() => setMode('truth')}
        style={{ position: 'absolute', top: 10, right: 10, padding: 10, cursor: 'pointer', background: '#4A90D9', color: '#fff', border: 'none', borderRadius: 4 }}
      >
        Truth View →
      </button>

      {selectedBuilding && (
        <div style={{ position: 'absolute', bottom: 20, left: 20, background: 'rgba(0,0,0,0.8)', color: '#eee', padding: 16, borderRadius: 8, fontFamily: 'monospace', maxWidth: 400 }}>
          <h3>{selectedBuilding}</h3>
          <button
            onClick={() => setSelectedBuilding(null)}
            style={{ float: 'right', cursor: 'pointer', background: 'none', border: 'none', color: '#fff' }}
          >
            ×
          </button>
          <p>Under Construction — coming in a future prompt</p>
        </div>
      )}
    </div>
  );
}
