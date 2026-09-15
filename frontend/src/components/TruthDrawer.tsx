'use client';

import { useState, type ReactNode } from 'react';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Building, WorldEntity } from '../types';

interface TruthDrawerProps {
  entityId: string | null;
  entities: WorldEntity[];
  buildings: Building[];
  onOpenChange: (open: boolean) => void;
  onFocus: (x: number, y: number) => void;
}

/** One plain number, with a tooltip defining it -- WORLD_CONSTITUTION.md's
 * W1.1: "no health bars for Sharpe, no invented composite scores." */
function MetricRow({ label, value, tooltip }: { label: string; value: ReactNode; tooltip: string }) {
  return (
    <div className="flex items-center justify-between border-b border-border/50 py-1.5 text-sm">
      <Tooltip>
        <TooltipTrigger className="cursor-help text-left text-muted-foreground underline decoration-dotted underline-offset-4">
          {label}
        </TooltipTrigger>
        <TooltipContent>{tooltip}</TooltipContent>
      </Tooltip>
      <span className="font-mono">{value}</span>
    </div>
  );
}

/** The persistent truth drawer (WORLD_CONSTITUTION.md's W1.1) -- a
 * right-side Sheet, not a mode toggle: the world stays visible behind it.
 * Content is driven entirely by real data. Only BUILDING and GOD ever have
 * content today (the only two live WorldEntityTypes, see
 * docs/WORLD_MAPPING.md) -- every field shown here traces to a real
 * backend value, and every "not tracked yet" / "not yet evaluated" line is
 * the honest absence of a table that doesn't exist yet, not a blank left
 * to look unfinished. */
export function TruthDrawer({ entityId, entities, buildings, onOpenChange, onFocus }: TruthDrawerProps) {
  const [copied, setCopied] = useState(false);
  const entity = entities.find((e) => e.entity_id === entityId) ?? null;
  const open = entity !== null;

  const building =
    entity?.entity_type === 'BUILDING' ? buildings.find((b) => `building:${b.id}` === entity.entity_id) : undefined;
  const godAtBuilding =
    entity?.entity_type === 'BUILDING'
      ? entities.find((e) => e.entity_type === 'GOD' && e.parent_entity_id === entity.entity_id)
      : undefined;
  const parentBuilding =
    entity?.entity_type === 'GOD' && entity.parent_entity_id
      ? buildings.find((b) => `building:${b.id}` === entity.parent_entity_id)
      : undefined;

  function copySource(): void {
    if (!entity) return;
    void navigator.clipboard.writeText(entity.source_entity_id);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        if (!next) onOpenChange(false);
      }}
    >
      <SheetContent side="right" className="w-full overflow-y-auto font-mono sm:max-w-md">
        {entity && (
          <>
            <SheetHeader>
              <SheetTitle className="capitalize">{entity.entity_id.replace(/[:_]/g, ' ')}</SheetTitle>
              <SheetDescription>{entity.source_entity_id}</SheetDescription>
            </SheetHeader>

            <div className="px-4 pb-4">
              <Button size="sm" variant="ghost" className="mb-3 h-6 px-2 text-xs" onClick={copySource}>
                {copied ? 'copied' : 'copy source id'}
              </Button>

              <div className="mb-3 flex items-center gap-2">
                {/* Type + state always shown as text/badge, never colour
                    alone -- W1.4's colour-blind requirement. */}
                <Badge variant="outline">{entity.entity_type}</Badge>
                <Badge>{entity.state}</Badge>
              </div>

              {building && (
                <>
                  <p className="mb-3 text-sm text-muted-foreground">{building.description}</p>
                  <MetricRow
                    label="Phase"
                    value={building.phase}
                    tooltip="Real construction_phase, derived from CONSTRUCTION_MANIFEST + activation-table row counts"
                  />
                  {building.prompt !== null && (
                    <MetricRow
                      label="Built in"
                      value={`Prompt ${building.prompt}`}
                      tooltip="Which backend prompt activates this building's table(s)"
                    />
                  )}
                  <MetricRow
                    label="Queue depth"
                    value={Number(entity.metrics.queue_depth ?? 0)}
                    tooltip="Pending jobs for this building. Always 0 today -- no jobs table exists yet (Prompt 4)."
                  />
                  <MetricRow
                    label="Throughput"
                    value="not tracked yet"
                    tooltip="No job-completion tracking exists yet (Prompt 4)"
                  />
                  <MetricRow
                    label="Component verdict"
                    value="not yet evaluated"
                    tooltip="component_registry.verdict does not exist yet (Prompt 6)"
                  />
                  {godAtBuilding && (
                    <MetricRow
                      label="God present"
                      value={godAtBuilding.entity_id.replace('god:', '')}
                      tooltip="The god whose identity IS this building -- renders whenever the building does"
                    />
                  )}
                </>
              )}

              {entity.entity_type === 'GOD' && (
                <>
                  <MetricRow
                    label="Stands at"
                    value={parentBuilding?.id ?? entity.parent_entity_id ?? '—'}
                    tooltip="The real building this god's presence mirrors"
                  />
                  {parentBuilding && <p className="mb-3 text-sm text-muted-foreground">{parentBuilding.description}</p>}
                </>
              )}

              {!building && entity.entity_type !== 'GOD' && (
                <p className="mb-3 text-sm text-muted-foreground">
                  No real backend source exists yet for this entity type -- see docs/WORLD_MAPPING.md.
                </p>
              )}

              <MetricRow
                label="Health"
                value={entity.health.toFixed(2)}
                tooltip="1.0 if ACTIVE, else 0.0 -- a real but currently binary signal, not a fabricated score"
              />
              <MetricRow
                label="Activity"
                value={entity.activity.toFixed(2)}
                tooltip="Structure.load -- always 0 today, no throughput tracking exists yet"
              />

              {building && (
                <Button className="mt-4 w-full" onClick={() => onFocus(building.location.x, building.location.y)}>
                  Focus camera
                </Button>
              )}
              {parentBuilding && (
                <Button className="mt-4 w-full" onClick={() => onFocus(parentBuilding.location.x, parentBuilding.location.y)}>
                  Focus camera
                </Button>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
