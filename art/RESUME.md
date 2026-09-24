# RESUME — Greek Rebuild

**Prompt pack:** Greek Rebuild R0–R12. **Current step:** R2 (style anchor).
**HUMAN GATE 1: cleared** — user approved treasury variation 0 (clean white
marble, terracotta roof, gold pediment).

**Account state:** PixelLab trial account #5 nearly exhausted (35/40 spent,
reconciled against `art/registry.json`; 5 remain, deliberately not spent —
see "Treasury" below). No jobs queued or running.

## Done this account, all pass `check_asset --key <key>` (law W11)

| Asset | Canvas | File |
|---|---|---|
| olive_tree | 32×48 | `art/raw/props/olive_tree.png` |
| cypress | 32×56 | `art/raw/props/cypress.png` |
| laurel_bush | 32×40 | `art/raw/props/laurel_bush.png` |
| herm_statue | 32×48 | `art/raw/props/herm_statue.png` |
| amphora_pair (now single amphora) | 32×32 | `art/raw/props/amphora_pair.png` |
| column_fragment | 32×32 | `art/raw/props/column_fragment.png` |
| stone_bench | 32×32 | `art/raw/props/stone_bench.png` |
| tripod_brazier | 32×40 | `art/raw/props/tripod_brazier.png` |
| plaza tile | 64×64 | `art/raw/tiles/plaza.png` (top face 64×41 → squash) |

All 8 props are done. R2's prop list is complete.

**Known imperfection (not a scale failure, not blocking):** most props still
carry a small square base/plinth despite `style_suffix_prop` asking for "no
ground, no plinth" — see `artifacts/gates/r2_props_scaled.png`. The instruction
reduces it but doesn't eliminate it. Acceptable for now; revisit if it looks
wrong once placed in the actual world (a plinth may even read fine sitting on
a tile). Not worth spending generations chasing before the treasury blocker
is resolved.

## NOT done: treasury final render

Two attempts both **FAIL** scale (need 163–202px content for the 3×3 backend
footprint):
- v1 (Gate 1 candidates, `art/raw/buildings/treasury_anchor_c0..c3.png`, 168
  canvas): 122px content.
- v2 (`art/raw/buildings/treasury_anchor_256.png`, 256 canvas via
  `create_1_direction_object`, 20 gens): 239px content — overshot.

**Finding:** `create_1_direction_object`'s canvas→content fill ratio is not
linear (73% fill at 168, 93% at 256) — do not guess a third canvas size.

**Next attempt: use `create_object_pro_flash` instead**, not
`create_1_direction_object`:
- Pass `style_image` = the approved `treasury_anchor_c0.png` (or its
  Backblaze URL if still valid) to lock the Gate-1 look.
- Try a custom canvas around 190–200px (`get_pro_flash_capabilities` is a
  FREE lookup — use it first; 180 and 192 both quoted 6 generations last
  session, 96 quoted 5 but is too small).
- Check with `python -m tools.art.check_asset <png> <canvas> --key treasury`
  after every attempt; budget 2–3 attempts (~12–18 gens) since the exact
  canvas-to-content relationship for this tool is still unverified.

## After treasury passes scale

1. Palette-lock `art/prompts.yaml`/pipeline to the final treasury (already
   using its palette + grass for all R2 props).
2. Implement the tile ingest squash (top face → 64×32) for grass/road/plaza —
   not built yet, doesn't block generation.
3. Build `artifacts/gates/gate1_style_board.png` v2 with the passing assets,
   confirm nothing else needs Gate 1 sign-off (style already approved; scale
   was a build-quality gate, not part of Gate 1 itself).
4. Move to R3. Before generating ANY character: character canvas/height has
   NO scale rule in `art/theme.yaml` yet (law W11 refuses it) — ask the user
   to decide character height in tiles first.

## On resume
- `get_balance` first; confirm a NEW account (0 used, not continuing #5's 35).
- Static art (tiles/props/buildings) can live on any account; characters must
  be created AND animated on the same account.
- Download URLs: pixflux `.../mcp/images/{job_id}/download`, iso tile
  `.../mcp/isometric-tile/{id}/download`, 1-direction object
  `.../mcp/objects/{id}/download` (pro-flash objects: check its own response
  for the download field). Always `curl -f -A "curl/8.0"`.
- Every job — including rejected/failed-scale ones — is logged in
  `art/registry.json` with `generations_spent`; the running total must equal
  `get_balance`'s `generations_used` after every batch.
