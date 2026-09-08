"use client';

import React, { useEffect, useState } from 'react';
import { fetchScoreboard } from './api';
import type { WorldState } from './types';

export function useScoreboard() {
  const [scoreboard, setScoreboard] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const sb = await fetchScoreboard();
        setScoreboard(sb);
      } catch (err) {
        console.error('Scoreboard fetch failed:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  return { scoreboard, loading };
}
