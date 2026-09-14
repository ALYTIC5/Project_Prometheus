'use client';

import { useEffect, useState } from 'react';
import { fetchWorldState } from '../../src/api';
import type { WorldEntity, WorldState } from '../../src/types';

/** Dev-only live view of the W0 WorldEntity contract, straight from
 * /world/state -- fetches the REAL backend, no mock data. Exists to make
 * the new contract visibly verifiable (is it actually populated? does every
 * entity trace to a real source?) without touching the Pixi renderer at
 * all. Every entity_type with no real backend source yet renders as an
 * explicit "0 -- awaiting Prompt N" line, never silently absent. */
export default function EntitiesPage() {
  const [world, setWorld] = useState<WorldState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchWorldState()
      .then((w) => {
        if (!cancelled) setWorld(w);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const byType = new Map<string, WorldEntity[]>();
  for (const entity of world?.entities ?? []) {
    const list = byType.get(entity.entity_type) ?? [];
    list.push(entity);
    byType.set(entity.entity_type, list);
  }

  const allTypes: WorldEntity['entity_type'][] = [
    'BUILDING', 'GOD', 'TEMPLE', 'HERO', 'AGENT', 'EXPERIMENT',
    'ARENA_MATCH', 'RESEARCH_SOURCE', 'PORTFOLIO', 'ALERT', 'REGIME', 'ARCHIVE_ENTRY',
  ];

  return (
    <div style={{ minHeight: '100vh', background: '#0a0a1a', color: '#eee', fontFamily: 'monospace', padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>World Entities</h1>
      <p style={{ color: '#888' }}>Live from /world/state -- {world?.entities.length ?? '...'} total.</p>
      {error && <p style={{ color: '#ff5555' }}>fetch failed: {error}</p>}
      {allTypes.map((type) => {
        const list = byType.get(type) ?? [];
        return (
          <section key={type} style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 14, color: list.length ? '#4A90D9' : '#555' }}>
              {type} ({list.length})
            </h2>
            {list.length === 0 && (
              <p style={{ fontSize: 12, color: '#555', margin: '4px 0' }}>
                no real backend source yet -- awaiting the prompt that builds it
              </p>
            )}
            {list.map((e) => (
              <div key={e.entity_id} style={{ fontSize: 12, padding: '2px 0', color: '#aaa' }}>
                {e.entity_id} — state={e.state} — source={e.source_entity_id}
                {e.parent_entity_id ? ` — parent=${e.parent_entity_id}` : ''}
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
