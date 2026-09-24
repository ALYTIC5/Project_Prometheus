# Art pipeline — RESUMED 2026-09-24

**Resumed:** 2026-09-24, user explicitly asked to continue the World
Track (pasted the full W0-W10 prompt doc and said "then build this").
The pause below is historical context, not current state.

**Account (token #1, `c6fc1a3a...`):** trial, 36/40 generations used, 4
remaining — confirmed still exhausted for planning purposes as of the
resume. **Do not spend these 4 on anything that needs a full 8-direction
character.**

## Decisions made at resume (2026-09-24)

- **Rotate to token #2 immediately**, before spending anything further on
  token #1. The user runs the two `claude mcp remove/add` commands in
  "Resume steps" below with their own next queued token value (never
  pasted into chat or any file) and restarts Claude Code.
- **Canvas size: standardize on 68x68.** 20 of 20 currently-live
  characters are already 68x68; the true-48x48 originals only survive as
  local export copies in `art/raw/characters/` from the dead old account.
  Going forward: generate everything at 68x68, and any place that still
  assumes 48x48 (docs/STYLE_BIBLE.md's own character-canvas number, once
  W1 writes it; building/prop scale ratios) must be sized against 68x68,
  not 48x48. The old 48x48 local copies get upscaled at ingest time if
  they're ever used, not treated as the master size.

## What's done (this account, token #1: `c6fc1a3a...`)

- **20 characters created**, confirmed via `list_characters`:
  - 12 agents + 3 harbour **recreated fresh** with their exact original
    prompts (agent_scribe, agent_scholar, agent_prophet, agent_engineer,
    agent_blacksmith, agent_experimenter, agent_statistician,
    agent_guardian, agent_auditor, agent_historian, agent_messenger,
    agent_necromancer, harbor_trader, harbor_courier, harbor_guard).
  - 5 new W4-Part-A characters (agent_builder, townsfolk_villager,
    townsfolk_merchant, townsfolk_pilgrim, dockhand).
  - All local static art downloaded to `art/raw/characters/<key>/idle/
    rotation/<direction>/0.png` — nothing left only on PixelLab's servers.
- **2 characters fully walk-cycled** (v3 mode, 8 directions, 8 frames):
  `agent_scribe` (job group `a61a6167-c33b-4208-8760-60f6dae80cdc`) and
  `agent_engineer` (job group `2b20fcee-436b-4e32-acdb-40ac442c77f2`).
  Downloaded to `art/raw/characters/<key>/idle/walk_v3/<direction>/
  {0..8}.png`.
- All of the above recorded in `art/registry.json` (local, gitignored).

## What remains

- **18 characters still need walk cycles** (all except agent_scribe/
  agent_engineer) — ~8 generations each, ~144 generations total across
  future accounts.
- **23 gods/heroes still need full recreation from scratch** — never
  started this session. ~23 `create_character` calls (~23 generations)
  before any of them can even be animated.

## Key findings from this session (read before resuming)

1. **PixelLab characters do not transfer between accounts at all.**
   `list_characters` on this account showed 0 before any creates, even
   though the OLD account had 15 real characters. This means multi-account
   rotation only helps for the **create** step (spreadable across
   accounts) — **animation of a character must happen on the same account
   that created it**, before that account's budget runs out. Plan future
   batches as create+animate together per account, in priority order —
   never assume a character created on one account can be animated on a
   different one later.
2. **Canvas size drifted.** This pipeline now produces 68x68 canvases
   regardless of the `size=48` param requested (both for recreated
   originals and new characters) — inconsistent with the true 48x48
   canvas the original 15 characters had on the old dead account.
   **RESOLVED 2026-09-24: standardize on 68x68** (see "Decisions made at
   resume" above).
3. **The old account's data is fully backed up locally already** — its
   38 characters' idle rotation art came bundled inside `Mockups.zip`
   itself (real export files, not just metadata), copied into
   `art/raw/characters/` by the Prompt-12-era pipeline before this
   session. Nothing further is retrievable from that account via API
   (23 of them are evicted/`not_found` server-side — only the local
   export copy exists for those).

## History: why this was paused (2026-09-18 → 2026-09-24)

Per explicit user instruction mid-session on 2026-09-18: all World Track
/ PixelLab art work was paused in favor of backend development. That
pause ended 2026-09-24 when the user explicitly asked to resume (see top
of this file).

## Next steps (in progress as of 2026-09-24)

1. **Waiting on the user** to rotate to token #2 themselves:
   ```
   claude mcp remove pixellab -s local
   claude mcp add pixellab https://api.pixellab.ai/mcp -t http -H "Authorization: Bearer <token #2>" -s local
   ```
   then restart Claude Code. The token value is never pasted into chat,
   a file, or a commit — only the user runs this.
2. Once restarted: `get_balance` + `list_characters` to confirm a fresh
   account (0 characters expected, per finding #1 above).
3. Canvas size is already resolved (68x68) — no re-litigation needed.
4. Continue: create the 23 gods/heroes (or a subset budget allows) AND
   animate them on the SAME account before it runs out, per finding #1.
   Then continue walk-cycling the 18 not-yet-animated agents/harbour on
   whichever account has budget, one full character at a time.
