# Art pipeline — PAUSED (account #2 exhausted, 2026-09-24)

**Paused at:** 2026-09-24, end of a full pantheon-recreation batch on
trial account #2.
**Account (token: `4ba4ead0...`, treat as compromised — echoed in chat
twice during rotation; rotate again before further use):** trial,
39/40 generations used, 1 remaining. Not enough for any further
create or animate call — treat as exhausted for planning.

**Note on this session:** ran from the `worktrees/random-forest-strategy`
git worktree, not the main checkout (harness would not allow git
operations against main from here). All local art state (registry.json,
raw/, etc.) was plain-file-copied from main into this worktree at session
start, then updated here. **Before further work, sync this worktree's
`art/` back into the main checkout** (plain copy, not git — these paths
are gitignored) so both stay consistent.

## What's done (account #2, this session)

- **23 characters created** at 96x96 (NOT 68x68 — canvas size drifted
  again despite requesting `size=68`; see finding #4 below), using their
  exact existing prompts from `art/registry.json` (all had been designed
  in an earlier session, never previously realized on PixelLab):
  - 8 gods: god_momentum, god_event_driven, god_evolution,
    god_machine_learning, god_macro, god_mean_reversion, god_stat_arb,
    god_value, god_volatility (9, not 8 — full canary+offensive+defensive
    pantheon roster).
  - 3 special: archive_keeper, oracle_validation, risk_guardian.
  - 11 heroes: hero_fast, hero_tank, hero_duelist, hero_mage (the 4 "v1"
    walking heroes) + hero_alchemist, hero_dormant, hero_hybrid,
    hero_rising, hero_rogue, hero_scout, hero_volatility (7 stationary
    skins).
  - All 23 x 8 rotation directions downloaded to
    `art/raw/characters/<key>/idle/rotation/<direction>/0.png`.
- **All 4 v1 heroes fully walk-cycled**, 4 directions each
  (south-east/south-west/north-east/north-west, matching the lean
  4-connected road-grid plan):
  - hero_fast, hero_tank, hero_duelist: `walking-8-frames` template mode,
    8 frames/direction. Downloaded to `art/raw/characters/<key>/idle/
    walk/<direction>/{0..7}.png`.
  - hero_mage: template mode failed 9/9 times ("heavy load") for this
    specific character — see finding #3. Fell back to v3 custom mode
    (`action_description="walking at a steady pace"`, frame_count=4,
    5 frames incl. reference), which worked on the first try for every
    direction. Downloaded to `art/raw/characters/hero_mage/idle/
    walk_v3/<direction>/{0..4}.png`.
- `art/registry.json` updated for all 23 characters (pixellab_id,
  account_status=exists, size=96, animations) and both walk-animation
  shapes above.
- Generation spend: 23 (creates) + 4+4+4 (fast/tank/duelist template
  walks, incl. free retries of "heavy load" failures) + 4 (mage v3 walks)
  = **39 of 40**, plus several uncharged failed attempts (PixelLab never
  bills a failed job).

## What remains

- **18 agents/harbour/townsfolk characters still need walk cycles**
  (everything from the account-#1 roster except agent_scribe/
  agent_engineer, which already have 8-direction walk_v3 cycles from a
  prior session) — they exist only on the NOW-EXHAUSTED account #1
  (`c6fc1a3a...`, 4 generations left there too) or need recreating fresh
  on a new account, per finding #1 below.
- **7 stationary heroes + 9 gods + 3 special characters are created but
  need NO further animation** — per W6's own design, gods/most heroes
  stand still using their rotation frames only. This is complete for the
  full roster now created.
- Canvas size is now 96x96 across every character on account #2 (not the
  68x68 this file previously said to standardize on) — needs another
  decision before atlas packing, see finding #4.
- Rotation frames + walk frames are all downloaded locally now (this
  session closed the "recorded metadata but never fetched the actual
  PNG" gap flagged mid-session), but **`art/raw/characters/` here lives
  in the worktree, not main** — sync before continuing (see top note).

## Key findings from THIS session (read before resuming)

1. **PixelLab characters still do not transfer between accounts.**
   Confirmed again: account #2 started at 0 characters despite account
   #1 having 20. Same rule as before — create AND animate on the same
   account before its budget runs out.
2. **Rotating tokens is easy to get wrong.** Twice this session a
   "rotation" actually re-submitted the SAME token as before (config
   never updated, or the wrong line copied from the token queue) —
   `get_balance`/`list_characters` coming back IDENTICAL after a rotation
   is the tell. Always verify with both calls after every rotation
   before spending anything.
3. **`walking-8-frames` TEMPLATE mode can fail hard for one specific
   character while working fine for others on the identical account/
   canvas/prompt-shape.** hero_mage failed "Generation failed due to
   heavy load" 9 times straight (4+4+1 attempts, all directions, all
   uncharged) while hero_fast/hero_tank/hero_duelist succeeded on the
   same account in the same window. Escalating to v3 custom mode
   (`action_description` instead of `template_animation_id`, lower
   `frame_count`) worked immediately. If template mode fails
   more than ~2-3 times for one character, stop retrying it and switch
   to v3 rather than continuing to burn wait time (failures are
   uncharged, so this costs no generations, only time).
4. **Canvas size drifted AGAIN, this time to 96x96.** Every one of the
   23 characters this session requested `size=68` (per the prior
   session's own "standardize on 68x68" decision) and every one came
   back 96x96 instead. This is now the SECOND different drift value
   observed (48 requested -> 68 actual in an earlier session; 68
   requested -> 96 actual this session). **The `size` parameter cannot
   be trusted to produce its requested value at all** — treat every
   future generation's actual size as unknown until checked via
   `get_character`, and do all cross-asset scale math (buildings, props,
   UI) against whatever the majority of LIVE characters actually measure
   at, re-verified each session, never against a requested value.
5. **Backblaze CDN URLs need a real User-Agent header.** Direct
   `urllib.request` downloads of `backblaze.pixellab.ai` asset URLs
   returned 403 Forbidden even though the exact same URL worked fine via
   `curl`. Fix: send `User-Agent: curl/8.0` (or any non-default UA) on
   every download request. The `?t=...` query param on these URLs is
   just a cache-buster, not a required auth token — safe to omit or keep.
6. **Metadata != downloaded assets.** `get_character`/`animate_character`
   responses give you URLs and let you update `registry.json`, but the
   actual PNG bytes are NOT fetched until you explicitly download them.
   A session can look complete (registry says "status: complete") while
   nothing has actually been pulled locally — confirm real files exist
   under `art/raw/` before considering any character done, every time.

## Next steps (when resuming)

1. Sync this worktree's `art/` directory back into the main checkout
   (plain file copy — these paths are gitignored, not a git operation):
   `art/registry.json`, `art/raw/characters/` (23 new character subdirs).
2. Rotate to a fresh account (token #3+), verifying with BOTH
   `get_balance` (expect 40/40 or close) AND `list_characters` (expect 0)
   before spending anything — per finding #2, don't trust a single check.
3. Re-measure actual canvas size on the first character created (finding
   #4) before doing any scale-dependent work.
4. Priority for the next account's budget: the 18 still-unanimated
   agents/harbour/townsfolk characters. They need recreating fresh
   (account #1's originals are unreachable for animation, exhausted at
   4 generations) — budget roughly 1 create + 4 template-walk generations
   each, ~90 generations for all 18, so this will span multiple accounts.
   If `walking-8-frames` template mode fails repeatedly (>2-3x) for any
   one character, switch that character to v3 mode immediately rather
   than retrying (finding #3).
5. Once agents are all walking: W5 (buildings) and W6's remaining backend
   work (world/pantheon.py derivation functions, temple_state rules,
   hero archetype mapping) can proceed — all 23 gods/heroes now exist
   with real character IDs to reference.
