'use client';

import { useBuildingsQuery, useScoreboardQuery, useViolationsQuery, useWorldStateQuery } from '../data/queries';
import { DashboardHeader } from './DashboardHeader';
import { LiveActivity } from './LiveActivity';
import { PipelineStatus } from './PipelineStatus';
import { ResearchSummary } from './ResearchSummary';
import { ViolationsBanner } from './ViolationsBanner';
import { BacktestScatterSection } from './sections/BacktestScatterSection';
import { BenchmarkChart } from './sections/BenchmarkChart';
import { CostsSection } from './sections/CostsSection';
import { DataSection } from './sections/DataSection';
import { ExperimentsSection } from './sections/ExperimentsSection';
import { LawsSection } from './sections/LawsSection';
import { PaperTradingSection } from './sections/PaperTradingSection';
import { QueueSection } from './sections/QueueSection';
import { StrategiesSection } from './sections/StrategiesSection';
import { SystemsTable } from './sections/SystemsTable';

const DASHBOARD_POLL_MS = 10000;
const HEADER_HEIGHT_PX = 72; // BenchmarkStrip (~36px) + the build-progress row (~36px)
const BANNER_HEIGHT_PX = 32;

/** PROMPT S -- the plain dashboard. Dense, fast, boring, useful (S.2).
 * Polls at 10s (S.3), reads the exact same /world/state, /buildings/,
 * /scoreboard/ the world view reads (S: "the backend contract never
 * drifts while the world is dormant"), plus the Prompt-4 endpoints
 * (/experiments/, /queue/, /violations/) that already have real data to
 * show, and /strategies/. */
export default function Dashboard() {
  const worldQuery = useWorldStateQuery(DASHBOARD_POLL_MS);
  const scoreboardQuery = useScoreboardQuery(DASHBOARD_POLL_MS);
  const buildingsQuery = useBuildingsQuery(DASHBOARD_POLL_MS);
  const violationsQuery = useViolationsQuery(DASHBOARD_POLL_MS);

  const world = worldQuery.data ?? null;
  const scoreboard = scoreboardQuery.data ?? null;
  const isError = worldQuery.isError || scoreboardQuery.isError || buildingsQuery.isError;
  const hasViolations = (violationsQuery.data?.violations.length ?? 0) > 0;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {hasViolations && (
        <div className="fixed inset-x-0 top-0 z-50">
          <ViolationsBanner />
        </div>
      )}
      {/*
        `transform` establishes a new containing block for `position:fixed`
        descendants (CSS spec) -- BenchmarkStrip's own `fixed top-0` (it is
        reused unmodified, not editable from here) resolves against THIS
        div instead of the viewport, letting the violations banner push the
        whole header stack down without touching that component.
      */}
      <div style={{ transform: hasViolations ? `translateY(${BANNER_HEIGHT_PX}px)` : 'none' }}>
        <DashboardHeader scoreboard={scoreboard} world={world} isError={isError} />
      </div>

      <main
        style={{ paddingTop: HEADER_HEIGHT_PX + (hasViolations ? BANNER_HEIGHT_PX : 0) }}
        className="mx-auto max-w-5xl pb-16"
      >
        {/*
          Always visible, not collapsible -- "what's the research doing
          right now" answered without opening anything. Real content
          (Strategies/Queue/Experiments/Benchmark) comes next; the two
          sections still genuinely awaiting a later prompt (Data, Costs)
          sink to the bottom so they never interrupt what's real today.
        */}
        <PipelineStatus />
        <LiveActivity />
        <ResearchSummary />
        <SystemsTable />
        <StrategiesSection />
        <QueueSection />
        <ExperimentsSection />
        <BacktestScatterSection />
        <BenchmarkChart />
        <PaperTradingSection />
        <LawsSection world={world} isLoading={worldQuery.isLoading} />
        <DataSection />
        <CostsSection />
      </main>
    </div>
  );
}
