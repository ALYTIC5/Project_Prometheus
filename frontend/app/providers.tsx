'use client';

import { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/** One QueryClient per browser session, stable across re-renders (useState
 * initializer runs once) -- a module-level singleton would leak state
 * across users on the server, but this app is a static export with no
 * server-side data fetching, so per-mount is simplest and correct here. */
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
