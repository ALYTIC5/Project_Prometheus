'use client';

import { useState, type ReactNode } from 'react';

interface SectionProps {
  /** localStorage key suffix -- collapsed state persists per section,
   * S.3: "Sections are collapsible and the state persists in localStorage." */
  storageKey: string;
  title: string;
  /** When true, renders the honest "Awaiting: <emptyLabel>" message
   * instead of children -- S.3: "Empty sections show 'Awaiting: <system>
   * — built in Prompt N' rather than hiding. Seeing what's missing is the
   * point." */
  isEmpty?: boolean;
  emptyLabel?: string;
  children: ReactNode;
}

function readCollapsed(key: string): boolean {
  try {
    return window.localStorage.getItem(`dashboard:${key}`) === 'collapsed';
  } catch {
    // Private browsing / blocked storage -- default open, never throw.
    return false;
  }
}

function writeCollapsed(key: string, collapsed: boolean): void {
  try {
    window.localStorage.setItem(`dashboard:${key}`, collapsed ? 'collapsed' : 'open');
  } catch {
    // Best-effort only -- a per-viewer convenience, not durable state.
  }
}

/** One collapsible section. Every SECTION in the dashboard spec is this
 * wrapper plus a body -- title, live status, collapse persistence, and
 * the empty-state message are handled once here, not per section. */
export function Section({ storageKey, title, isEmpty, emptyLabel, children }: SectionProps) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(storageKey));

  function toggle(): void {
    setCollapsed((prev) => {
      const next = !prev;
      writeCollapsed(storageKey, next);
      return next;
    });
  }

  return (
    <section className="border-b border-border">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        className="flex w-full items-center justify-between px-4 py-2 text-left font-mono text-xs font-semibold tracking-wide text-muted-foreground uppercase hover:text-foreground"
      >
        <span>{title}</span>
        <span aria-hidden="true">{collapsed ? '+' : '−'}</span>
      </button>
      {!collapsed && (
        <div className="px-4 pb-4">
          {isEmpty ? (
            <p className="py-2 font-mono text-sm text-muted-foreground">
              Awaiting: {emptyLabel}
            </p>
          ) : (
            children
          )}
        </div>
      )}
    </section>
  );
}
