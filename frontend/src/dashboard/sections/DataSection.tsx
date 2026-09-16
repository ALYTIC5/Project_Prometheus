'use client';

import { Section } from './Section';

/** SECTION 3 -- DATA. Genuinely gated on Prompt 2: there is no /data
 * route, no ingestion has run against production, and no per-symbol bar
 * counts are exposed anywhere today. Unlike EXPERIMENTS/QUEUE (Prompt 4,
 * already built, wired to real endpoints), this section really is
 * "awaiting" -- the honest empty state, not a placeholder for something
 * that already exists. */
export function DataSection() {
  return (
    <Section
      storageKey="data"
      title="Data"
      isEmpty
      emptyLabel="Library — ingest timestamps, bar counts, data_version, quality checks — built in Prompt 2"
    >
      <></>
    </Section>
  );
}
