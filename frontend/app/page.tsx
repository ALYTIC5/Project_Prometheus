'use client';

import dynamic from 'next/dynamic';

// PROMPT S: UI_MODE=plain|world, defaulting to plain -- the isometric
// world is preserved intact (frontend/src/world/), not deleted, and both
// modes read the exact same /world/state contract. NEXT_PUBLIC_ (not bare
// UI_MODE): next.config.js's output:'export' makes this a build-time
// static export, so only NEXT_PUBLIC_* vars are readable client-side --
// same reasoning as this project's existing NEXT_PUBLIC_SPRITE_SET.
const UI_MODE = process.env.NEXT_PUBLIC_UI_MODE ?? 'plain';

// PixiJS needs a real canvas/window — never render this on the server.
const WorldView = dynamic(() => import('../src/world/WorldView'), { ssr: false });
// Dynamic (not a plain import) too, so whichever mode isn't selected never
// loads its JS chunk at runtime -- keeps pixi.js out of the plain
// dashboard's bundle and vice versa.
const Dashboard = dynamic(() => import('../src/dashboard/Dashboard'), { ssr: false });

export default function Home() {
  return UI_MODE === 'world' ? <WorldView /> : <Dashboard />;
}
