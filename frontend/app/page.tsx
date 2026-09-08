'use client';

import dynamic from 'next/dynamic';

// PixiJS needs a real canvas/window — never render this on the server.
const WorldView = dynamic(() => import('../src/components/WorldView'), { ssr: false });

export default function Home() {
  return <WorldView />;
}
