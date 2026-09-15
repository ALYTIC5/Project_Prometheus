'use client';

import { useEffect, useState } from 'react';
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import type { WorldEntity } from '../types';

interface SearchPaletteProps {
  entities: WorldEntity[];
  onSelect: (entity: WorldEntity) => void;
}

/** Cmd/Ctrl-K command palette (WORLD_CONSTITUTION.md's W1.3). Searches
 * every real WorldEntity -- today that's BUILDING + GOD; it grows
 * automatically as later prompts populate HERO/EXPERIMENT/etc, no changes
 * needed here. Selecting a result flies the camera AND opens the drawer,
 * both, always (the caller's onSelect does both) -- per spec, doing only
 * one turns the world into a navigation maze. */
export function SearchPalette({ entities, onSelect }: SearchPaletteProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  const byType = new Map<string, WorldEntity[]>();
  for (const entity of entities) {
    const list = byType.get(entity.entity_type) ?? [];
    list.push(entity);
    byType.set(entity.entity_type, list);
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title="Search the world"
      description="Jump to any real entity -- building, god, and (once real) strategy/experiment/family"
    >
      <CommandInput placeholder="Search buildings, gods, strategy IDs, reason codes..." />
      <CommandList>
        <CommandEmpty>No matching entity.</CommandEmpty>
        {Array.from(byType.entries()).map(([type, list]) => (
          <CommandGroup key={type} heading={type}>
            {list.map((entity) => (
              <CommandItem
                key={entity.entity_id}
                value={`${entity.entity_id} ${entity.source_entity_id} ${entity.state}`}
                onSelect={() => {
                  setOpen(false);
                  onSelect(entity);
                }}
              >
                {entity.entity_id}
                <span className="ml-2 text-muted-foreground">{entity.state}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
