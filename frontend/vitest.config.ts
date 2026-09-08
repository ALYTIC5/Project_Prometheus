import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Pure-math modules only (iso/, layout/) -- no DOM/canvas needed, so no
    // jsdom/happy-dom dependency. Pixi/React rendering is verified manually
    // in-browser, per the plan's verification section.
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
