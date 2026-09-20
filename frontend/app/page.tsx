'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';

type UiMode = 'plain' | 'world';

// PROMPT S: NEXT_PUBLIC_UI_MODE (build-time, next.config.js's
// output:'export') still picks which view loads on first paint --
// matches layout.tsx's server-rendered body style so there's no flash of
// the wrong background. A viewer can flip it at runtime with the button
// below; that choice is remembered in localStorage, per browser, not
// baked into the deploy.
const BUILD_DEFAULT_MODE: UiMode = process.env.NEXT_PUBLIC_UI_MODE === 'world' ? 'world' : 'plain';
const STORAGE_KEY = 'prometheus_ui_mode';

// PixiJS needs a real canvas/window — never render this on the server.
const WorldView = dynamic(() => import('../src/world/WorldView'), { ssr: false });
// Dynamic (not a plain import) too, so whichever mode isn't currently
// shown never loads its JS chunk until the viewer actually switches to it.
const Dashboard = dynamic(() => import('../src/dashboard/Dashboard'), { ssr: false });

function applyBodyStyle(mode: UiMode) {
  // Mirrors layout.tsx's build-time bodyStyle -- the world's fixed dark
  // canvas fights a scrolling plain dashboard, so switching modes at
  // runtime has to flip these the same way a rebuild would.
  document.body.style.background = mode === 'world' ? '#0a0a1a' : '';
  document.body.style.overflow = mode === 'world' ? 'hidden' : '';
}

export default function Home() {
  const [mode, setMode] = useState<UiMode>(BUILD_DEFAULT_MODE);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'plain' || stored === 'world') setMode(stored);
  }, []);

  useEffect(() => {
    applyBodyStyle(mode);
    window.localStorage.setItem(STORAGE_KEY, mode);
  }, [mode]);

  return (
    <>
      <button
        type="button"
        onClick={() => setMode((m) => (m === 'world' ? 'plain' : 'world'))}
        className="fixed right-3 top-3 z-[9999] rounded border border-neutral-600 bg-neutral-900/90 px-3 py-1.5 font-mono text-xs font-semibold text-neutral-100 shadow-lg hover:bg-neutral-800"
      >
        {mode === 'world' ? 'Text view' : 'World view'}
      </button>
      {mode === 'world' ? <WorldView /> : <Dashboard />}
    </>
  );
}
