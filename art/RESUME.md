# Art pipeline — PAUSE (PixelLab credits exhausted)

**Paused at:** 2026-09-18, after W4 pilot batch.
**Account:** trial, 40/40 generations used, $0.00 balance, 0 remaining.
**Confirmed via:** `get_balance` -> `generations_remaining: 0`.

## What's done

- W0 (tooling check, ingest pipeline, art roster) — complete, see
  `docs/ART_ROSTER.md`, commit `c4a7cac`.
- W4 pilot: walk-cycle mode decision. Ran both PixelLab modes on
  `agent_scribe` (character_id `d36c0bd2-a3ca-4f12-9b31-c85cb21a93f9`):
  - `walk_template_pilot` — template mode, `walking-8-frames`, all 8
    directions, 8 generations, job group `ff0e3672-8319-49a4-834b-f6dfa5fe1d1e`.
  - `walk_v3_pilot` — v3 custom mode, south-east only, 8 frames,
    1 generation, job group `8d257c55-710d-4163-a804-eb6fea350b76`.
  - Both recorded in `art/registry.json`'s `agent_scribe.animations`
    (local only, gitignored — rebuild via ingest if this file is ever lost,
    the job IDs above are the source of truth).
  - Decision written to `docs/ART_DECISIONS.md`: **use v3 mode for future
    walk cycles**, with the action_description made explicit about the
    held prop (e.g. "carrying a sealed scroll, no weapon") to prevent the
    identity drift the pilot observed in v3's default prompt.

## What's queued

Nothing queued — both pilot jobs completed and were ingested before the
account ran out (no half-finished animation groups to resume).

## What remains (real W4 batch, once a working account exists)

Per `docs/ART_ROSTER.md`'s gap analysis, on a **fresh account** (this
one's account_status data — 12/12 agents, 3/3 harbour exist; 0/12 gods,
0/11 heroes — should be re-verified with `list_characters` in case the
new account is the SAME PixelLab account resurrected, not a different
one; if the god/hero characters are gone there too, it's the account, not
this trial cycling):

1. **W4 Part A — new characters** (no existing PixelLab record, must use
   `create_character`, not `animate_character`):
   - `agent_builder` (AgentRole.BUILDER has no mockup art yet)
   - 3 ambient townsfolk: `townsfolk_villager`, `townsfolk_merchant`,
     `townsfolk_pilgrim` (cosmetic only, Law W2 — never signal-bearing)
   - `dockhand` (harbour NPC, no AgentRole)
2. **W4 Part B — walk cycles for the 15 still-existing characters**
   (12 agents + 3 harbour), using v3 mode per the pilot decision above,
   prop-explicit prompts per character (check each character's own
   `prompt` field in `art/registry.json` for what it's holding/wearing
   before writing the action_description).
3. **Harbour duplicate-prompt fix** — `harbor_courier` and `harbor_guard`
   share verbatim prompt text with `agent_messenger`/`agent_guardian`
   (see `docs/ART_ROSTER.md`). Regenerate with real sailor/dockhand
   prompts — `create_character` cost, bundle with Part A if budget allows.
4. **23-character recreation** (all gods, all heroes) — full
   `create_character` cost, much larger spend than animation; the
   session already flagged ~35-40 total trial-account cycles needed for
   the whole pipeline at this account's generation budget.

Estimated generations still needed: unchanged from `docs/ART_ROSTER.md`'s
prior estimate — nowhere near coverable by a single trial account, hence
the multi-account rotation already agreed with the user.

## Resume steps

1. Rotate to the next queued PixelLab trial account. Update the token via
   environment variable, never paste it into a repo file, log, or commit
   (Law W9):
   ```
   claude mcp add pixellab https://api.pixellab.ai/mcp -t http -H "Authorization: Bearer <token>"
   ```
2. Restart Claude Code so the new MCP connection takes effect.
3. Call `get_balance` first — confirm it's a fresh/different balance than
   0/40 exhausted.
4. Call `list_characters` — **compare against this account's roster**
   (12 agents, 3 harbour, 0 gods, 0 heroes). If the new account shows the
   SAME roster, it's the same underlying PixelLab account (unexpected —
   re-verify token rotation actually worked). If it shows a different
   roster (likely empty, since these are fresh trial signups), proceed —
   this is a new account and none of the existing character_ids are
   valid on it; the god/hero/townsfolk/builder/dockhand characters must
   be created fresh here via `create_character`, not referenced by the
   old character_ids.
5. No partial animation groups to fill (see "What's queued" above) —
   start directly on the W4 batch per "What remains."
6. Continue from here; this file gets rewritten (not appended) at the
   next pause.
