'use client';

import { useState } from 'react';
import { useResearchPapersQuery } from '../../data/queries';
import type { ResearchPaperRow } from '../../types';
import { DetailModal, type DetailTarget } from '../DetailModal';
import { Section } from './Section';

const DASHBOARD_POLL_MS = 10000;

function PaperRow({ paper, onClick }: { paper: ResearchPaperRow; onClick: () => void }) {
  return (
    <tr onClick={onClick} className="cursor-pointer border-b border-border/50 hover:bg-muted/40">
      <td className="py-1.5 pr-4 text-muted-foreground">{paper.arxiv_id}</td>
      <td className="py-1.5 pr-4">{paper.title}</td>
      <td className="py-1.5 pr-4 text-muted-foreground">
        {new Date(paper.ingested_at).toLocaleDateString()}
      </td>
    </tr>
  );
}

/** SECTION -- RESEARCH PAPERS (the Library). Every paper the daily
 * arXiv q-fin.* search has ever ingested (GET /research-papers/, real
 * count, not the 5-recent glance LiveActivity already shows) -- title,
 * arXiv id, ingestion date, click for the real abstract. Honest about
 * the fixed category filter's own breadth: q-fin.* pulls every
 * quantitative-finance subfield (stochastic calculus, option pricing
 * theory, market microstructure...), not specifically trading-strategy
 * papers, so most titles here are theoretical, not directly
 * actionable -- that is what the real search actually returns, not a
 * curation failure. */
export function ResearchPapersSection() {
  const { data, isLoading } = useResearchPapersQuery(DASHBOARD_POLL_MS);
  const papers = data?.papers ?? [];
  const [target, setTarget] = useState<DetailTarget | null>(null);

  return (
    <Section
      storageKey="research-papers"
      title={`Research papers read (${data?.total ?? 0})`}
      description="Library: every paper the daily arXiv q-fin.* search has ever ingested. Click a row for its real abstract."
      isEmpty={!isLoading && papers.length === 0}
      emptyLabel="Library — no papers ingested yet (daily llm_ingestion concern, arXiv q-fin.* search)"
    >
      {isLoading ? (
        <p className="py-2 font-mono text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-border text-muted-foreground uppercase">
                <th className="py-1.5 pr-4 font-medium">arXiv ID</th>
                <th className="py-1.5 pr-4 font-medium">Title</th>
                <th className="py-1.5 pr-4 font-medium">Ingested</th>
              </tr>
            </thead>
            <tbody>
              {papers.map((paper) => (
                <PaperRow
                  key={paper.id}
                  paper={paper}
                  onClick={() => setTarget({ kind: 'paper', paper })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <DetailModal target={target} onClose={() => setTarget(null)} />
    </Section>
  );
}
