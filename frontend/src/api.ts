import type { Building, ScoreboardResponse, WorldState } from './types';

// Empty string is a deliberate, valid value (production: frontend and API
// share one origin, so relative paths like "/world/state" are correct) --
// `??` rather than `||` so it isn't mistaken for "unset" and overridden.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function fetchWorldState(): Promise<WorldState> {
  const res = await fetch(`${API_BASE}/world/state`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`World state fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchBuildings(): Promise<{ buildings: Building[]; total: number }> {
  const res = await fetch(`${API_BASE}/buildings/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Buildings fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchScoreboard(): Promise<ScoreboardResponse> {
  const res = await fetch(`${API_BASE}/scoreboard/`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Scoreboard fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchDrilldown(
  entityType: string,
  entityId: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/world/drilldown/${entityType}/${entityId}`, { cache: 'no-store' });
  if (!res.ok) throw new Error(`Drilldown fetch failed: ${res.status}`);
  return res.json();
}

export function createWorldSocket(onMessage: (state: WorldState) => void): WebSocket {
  // API_BASE === "" means same-origin (production); derive ws(s):// from
  // the current page instead of blindly replacing a "http" substring that
  // won't exist in an empty string.
  const wsBase = API_BASE === '' ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}` : API_BASE.replace('http', 'ws');
  const ws = new WebSocket(`${wsBase}/world/deltas`);
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
