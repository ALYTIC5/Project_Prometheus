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

## On resume
- `get_balance` first; confirm it is a NEW account (account #4 shows 0 remaining).
- Static art (tiles/props/buildings) can live on any account; characters must be
  created and animated on the same account.
- Download URLs: pixflux `https://api.pixellab.ai/mcp/images/{job_id}/download`,
  iso tile `https://api.pixellab.ai/mcp/isometric-tile/{id}/download` (use `curl -f`).
