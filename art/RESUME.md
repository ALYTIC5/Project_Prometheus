# Art pipeline — PAUSED (account #3, PixelLab service degraded, 2026-09-24)

**Paused at:** 2026-09-24, mid-batch on trial account #3, stopped by
explicit user choice after 3 consecutive "heavy load" failure rounds
(service-side degradation, not a budget or account problem).
**Account (token: `65f9f860...`, then `<latest>` — multiple tokens used
this session, all echoed in chat at some point, treat all as
compromised):** trial, 28/40 generations used, 12 remaining. Budget is
fine; PixelLab's generation service was failing most jobs when this
session stopped.

**Note on this session:** ran from the `worktrees/random-forest-strategy`
git worktree, not the main checkout (harness will not allow git
operations against main from a worktree session). All local art state
was plain-file-copied from main into this worktree at session start,
updated here, then **synced back to main at end of session** (see
finding #7 — this sync has a real gotcha).

## What's done (account #3, this session)

Recreated 8 of the 18 remaining not-yet-walking characters from account
#1's original roster, using their exact existing prompts. All 8 exist at
96x96 (see prior finding on canvas-size drift), rotation frames
downloaded for all 8:

- **Fully walk-cycled (4/4 directions)**: agent_builder (2 directions
  template mode + 2 directions v3 mode, mixed after template kept
  failing), agent_statistician, agent_guardian, agent_auditor (all 4
  pure template mode, no fallback needed).
- **Partially walk-cycled (2/4 directions)**: agent_necromancer
  (south-east/south-west done, north-east/north-west still failing
  when the session stopped), harbor_trader (north-east/north-west done,
  south-east/south-west still failing).
- **Created, zero walk cycles yet**: agent_experimenter, harbor_courier
  (harbor_courier itself needed 5 create attempts before one succeeded —
  see finding #6).
- `art/registry.json` updated for all 8 (pixellab_id, account_status,
  size=96, animations — including the two partial ones marked
  `partial_missing_north`/`partial_missing_south` so a future session
  knows exactly which directions remain).
- 218 PNG files downloaded and verified (218/218, cross-checked against
  the exact expected count per character before moving on).
- Spend: 8 creates (some needed retries, only successes billed) + 4+4+4+4
  (builder/statistician/guardian/auditor walks) + 2+2 (necromancer/
  harbor_trader partial walks) = 28 of 40 generations used.

## What remains

- **10 characters still need recreating from scratch** on a future
  account (everything from the account-#1 roster except agent_scribe/
  agent_engineer, done long ago, and the 8 done this session):
  agent_historian, agent_messenger, agent_prophet, agent_scholar,
  agent_blacksmith, harbor_guard, dockhand, townsfolk_villager,
  townsfolk_merchant, townsfolk_pilgrim. Per W4's own design these are
  ALL stationary/courier-marker fallback characters (no walk needed) —
  create-only, ~1 generation each, ~10 generations total whenever a
  session has spare budget.
- **2 characters need their remaining 2 walk directions finished**:
  agent_necromancer (north-east, north-west) and harbor_trader
  (south-east, south-west) — do these FIRST on the next session, before
  any new character, since they're already 2/4 done and the character
  objects already exist on account #3 (12 generations still on that
  account, if it's still the active one).
- **2 characters need their first walk cycle (4 directions each)**:
  agent_experimenter, harbor_courier.
- The full pantheon (23 gods/heroes/special from the prior session) is
  complete and needs no further PixelLab work — only W5/W6 backend and
  temple-building work remains for those.

## Key findings from THIS session (read before resuming)

1. **Verify token rotation with BOTH `get_balance` AND `list_characters`
   after every single rotation, not just once.** This session needed
   THREE rotation attempts before landing on a genuinely fresh account —
   attempt 1 pasted the same token twice (typo/copy error), attempt 2
   the user hadn't restarted Claude Code yet, only attempt 3 worked.
   Each wrong attempt looked identical to the last until both checks
   were run.
2. **PixelLab's generation service can degrade mid-session, independent
   of account budget.** Near the end of this session, ~80% of both
   create_character and animate_character calls failed with "Generation
   failed due to heavy load" — across multiple different characters, both
   template and v3 animation modes, and even on a plain `create_character`
   retry. This was NOT the character-specific issue seen with hero_mage
   last session (finding carried over below) — it affected everything
   uniformly for a sustained period. When this happens: retries are still
   free (failures are never billed) but stop being productive; the
   session paused rather than keep burning turns. If it recurs, try again
   after a real time gap (minutes, not seconds) rather than immediate
   back-to-back retries.
3. **A single character CAN still fail specifically even when the
   service is otherwise healthy** (carried over from last session):
   template mode failing 3+ times for one character while others succeed
   in the same window means switch that one character to v3 custom mode
   rather than keep retrying template.
4. **Canvas size is still 96x96 on this account too** (third different
   drift value across three sessions: 48 requested->68 actual, then
   68->96, now 68->96 again but confirmed stable within an account at
   least). Treat requested `size` as advisory only, always confirmed via
   `get_character` after the fact.
5. **Backblaze CDN URLs need `User-Agent: curl/8.0`** (or any non-default
   UA) or they 403 — carried over from last session, still true this
   session on the new account's own CDN path prefix.
6. **A single character's create can fail specifically for several
   retries even during otherwise-normal service** (harbor_courier needed
   5 attempts, including one prompt reword, before succeeding — this was
   BEFORE the broader service degradation started, so it really was
   character/timing-specific, not the same root cause as finding #2).
7. **`Copy-Item -Recurse -Force` NESTS instead of merging when the
   destination folder already exists.** Syncing this session's new
   character folders back to main with `Copy-Item -Recurse -Force
   "...worktree\art\raw\characters\agent_builder"
   "...main\art\raw\characters\agent_builder"` — where
   `agent_builder` already existed in main from account #1's original
   creation — produced
   `main/art/raw/characters/agent_builder/agent_builder/idle/...`
   (nested duplicate) instead of overwriting
   `main/art/raw/characters/agent_builder/idle/...` in place. The STALE
   old content was left untouched at the top level; the NEW content was
   buried one level deeper. Caught by counting PNG files (got 282,
   expected 218 — the diff was exactly 64, i.e. 8 characters x 8 stale
   rotation frames each) and fixed by deleting the stale top-level
   `idle/` and promoting the nested one up. **Going forward: when syncing
   a character folder that might already exist in the destination, `rm
   -rf` the destination subfolder FIRST (plain Bash, not PowerShell), then
   copy — never rely on Copy-Item's merge behavior for anything that
   already exists.** Always verify post-sync file counts match the
   pre-sync source count exactly before trusting a sync.

## Next steps (when resuming)

1. Confirm account state first: `get_balance` + `list_characters` (both).
   If it's still account #3 with ~12 generations, continue there;
   otherwise rotate to a fresh one (verify both checks per finding #1).
2. If PixelLab's service was degraded when this session stopped, do a
   single test `get_balance`-then-`create_character` probe before queueing
   anything larger, to confirm it has recovered.
3. Priority order for whatever budget is available:
   a. Finish agent_necromancer's north-east/north-west (2 generations).
   b. Finish harbor_trader's south-east/south-west (2 generations).
   c. Walk-cycle agent_experimenter (1 create already done + 4 walk
      generations).
   d. Walk-cycle harbor_courier (1 create already done + 4 walk
      generations).
   e. Create (no walk needed) the remaining 10 stationary characters:
      agent_historian, agent_messenger, agent_prophet, agent_scholar,
      agent_blacksmith, harbor_guard, dockhand, townsfolk_villager,
      townsfolk_merchant, townsfolk_pilgrim.
4. After every character folder sync from a worktree to main, `rm -rf`
   the destination subfolder before copying (finding #7) and verify file
   counts match.
5. Once all agents/harbour/townsfolk exist: W5 (buildings) and W6's
   remaining backend work can proceed using the full, now-complete
   character roster.
