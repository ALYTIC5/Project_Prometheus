# RESUME — Greek Rebuild

**Prompt pack:** Greek Rebuild R0–R12. **Current step:** R2 (style anchor), stopped at
**HUMAN GATE 1** (T4). Nothing past R2 may start until the user replies "approved"
with a chosen treasury variation.

**Account state:** PixelLab trial account #4 is exhausted (40/40 spent, reconciled
against `art/registry.json`). No jobs are queued or running. Every job ID is in the
registry, tagged `trial_account_4`.

## Done (all downloaded to disk; `art/raw/` and `artifacts/` are gitignored)

| Asset | File | Status |
|---|---|---|
| Treasury anchor ×4 (168px) | `art/raw/buildings/treasury_anchor_c0..c3.png` | awaiting Gate 1 pick (recommended: c0) |
| Grass tile, block | `art/raw/tiles/grass_calibration.png` | top face 64×36 |
| Grass tile, thin | `art/raw/tiles/grass_thin.png` | top face 64×28 |
| Grass tile, thick | `art/raw/tiles/grass_thick.png` | top face 64×38 |
| Road tile | `art/raw/tiles/road.png` | good, 64×36 → squash |
| Props ×6 (64px, pixflux, palette-forced) | `art/raw/props/{olive_tree,cypress,tripod_brazier,stone_bench,herm_statue,laurel_bush}.png` | check_asset OK |
| Rejected | `art/raw/props/*_rejected.png`, `amphora_pair.png`, `column_fragment.png`, `art/raw/tiles/plaza_rejected.png` | kept for reference |
| Gate boards | `artifacts/gates/gate1_{temple_candidates,style_board,props,rerolls}.png` | |

## Remaining for R2 (estimated 3–6 generations on the next account)

1. Add a props-specific style suffix to `art/prompts.yaml` (no "terracotta roof tiles"),
   route `compose()` props to it, keep lint green.
2. Re-run `amphora_pair` and `column_fragment` via `create_image_pixflux`
   (1 gen each, 64px, isometric, forced palette from chosen anchor + grass).
3. Re-run `plaza` tile (`create_isometric_tile`, 1 gen).
4. Implement the ingest squash (top face → 64×32) for tiles.
5. Palette-lock after the Gate 1 pick; if the pick is not c0, remap props locally.
6. **Scale (law W11 — run `preflight` before every job, `check_asset --key` after):**
   - All 8 props: regenerate on a 32 px canvas (~8 gens, pixflux).
   - Treasury anchor FAILS scale (122 px vs 192 px for its backend 3×3
     footprint). Gate 1 is a STYLE gate, so the user can still pick a look,
     but the shipped treasury must be regenerated on a 256 canvas
     (`create_1_direction_object` size 256 = 1 candidate, ~20–40 gens).
   - Characters have no scale rule: ask the user to decide the character
     height (in tiles) before R3.
   Total remaining for R2: ~10–12 gens + the treasury re-render.

## On resume
- `get_balance` first; confirm it is a NEW account (account #4 shows 0 remaining).
- Static art (tiles/props/buildings) can live on any account; characters must be
  created and animated on the same account.
- Download URLs: pixflux `https://api.pixellab.ai/mcp/images/{job_id}/download`,
  iso tile `https://api.pixellab.ai/mcp/isometric-tile/{id}/download` (use `curl -f`).
