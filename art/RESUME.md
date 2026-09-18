# Art pipeline — PAUSED (World Track on hold, backend work takes priority)

**Paused at:** 2026-09-18, end of W4 character batch on trial account #1.
**Account:** trial, 36/40 generations used, 4 remaining (not enough for
another full 8-direction character — treat as exhausted for planning).

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
   canvas the original 15 characters had on the old dead account. Needs a
   normalization decision (resize at ingest vs. accept 68px as the new
   standard) before atlas packing. Not resolved — flagged for whoever
   resumes this.
3. **The old account's data is fully backed up locally already** — its
   38 characters' idle rotation art came bundled inside `Mockups.zip`
   itself (real export files, not just metadata), copied into
   `art/raw/characters/` by the Prompt-12-era pipeline before this
   session. Nothing further is retrievable from that account via API
   (23 of them are evicted/`not_found` server-side — only the local
   export copy exists for those).

## PAUSED — do not resume without explicit user request

Per explicit user instruction mid-session: **all World Track / PixelLab
art work is paused in favor of backend development.** Do not rotate to
the next account, do not spend any more PixelLab generations, even though
9 more account tokens are queued and ready. Wait for the user to
explicitly ask to resume the World Track before touching this again.

## Resume steps (when the user asks to continue)

1. Rotate to token #2:
   ```
   claude mcp remove pixellab -s local
   claude mcp add pixellab https://api.pixellab.ai/mcp -t http -H "Authorization: Bearer <token #2>" -s local
   ```
2. Restart Claude Code.
3. `get_balance` + `list_characters` to confirm a fresh account (0
   characters expected, per finding #1 above).
4. Resolve finding #2 (canvas size) before generating anything new.
5. Continue: create the 23 gods/heroes (or a subset budget allows) AND
   animate them on the SAME account before it runs out, per finding #1.
   Then continue walk-cycling the 18 not-yet-animated agents/harbour on
   whichever account has budget, one full character at a time.
