import { useEffect, useState } from 'react';

/** WORLD_CONSTITUTION.md's W1.4 hard requirement: respect
 * prefers-reduced-motion -- idle animation, camera drift, and weather
 * become instant/static rather than animated. There is no camera drift or
 * weather in this renderer yet (honest: nothing to disable there); this
 * currently gates the builders' idle bob and the selection-outline pulse,
 * both of which are pure functions of an elapsed-time argument, so freezing
 * it at a constant is sufficient -- no changes needed inside render/*.ts. */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(query.matches);
    const onChange = (e: MediaQueryListEvent): void => setReduced(e.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  return reduced;
}
