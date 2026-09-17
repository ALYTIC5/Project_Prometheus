'use client';

import { Section } from './Section';

/** SECTION 8 -- COSTS. No cost-tracking table exists yet (llm_usage /
 * Railway usage estimate are Prompt 10's monitoring layer). Genuinely
 * empty, same reasoning as DataSection. */
export function CostsSection() {
  return (
    <Section
      storageKey="costs"
      title="Costs"
      description="Watchtower: Railway hosting usage + LLM API spend, weighed against benchmark excess."
      isEmpty
      emptyLabel="Watchtower — Railway usage estimate + LLM spend vs. benchmark excess — built in Prompt 10"
    >
      <></>
    </Section>
  );
}
