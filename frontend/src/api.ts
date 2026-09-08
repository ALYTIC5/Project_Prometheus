import { WorldState } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchWorldState(): Promise<WorldState> {
  const res = await fetch(`${API_BASE}/world/state`, {
    next: { revalidate: 5 },
  });
  if (!res.ok) throw new Error(`World state fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchBuildings() {
  const res = await fetch(`${API_BASE}/buildings/`);
  if (!res.ok) throw new Error(`Buildings fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchScoreboard() {
  const res = await fetch(`${API_BASE}/scoreboard/`);
  if (!res.ok) throw new Error(`Scoreboard fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchDrilldown(entityType: string, entityId: string) {
  const res = await fetch(`${API_BASE}/world/drilldown/${entityType}/${entityId}`);
  if (!res.ok) throw new Error(`Drilldown fetch failed: ${res.status}`);
  return res.json();
}

export function createWorldSocket(onMessage: (state: WorldState) => void): WebSocket {
  const ws = new WebSocket(`${API_BASE.replace('http', 'ws')}/world/deltas`);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'world_update') {
        onMessage(msg.data as WorldState);
      }
    } catch {
      // ignore parse errors
    }
  };
  return ws;
}
