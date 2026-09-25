# RESUME — Greek Rebuild

**Prompt pack:** Greek Rebuild R0–R12. **R2 (style anchor) is DONE.**
**HUMAN GATE 1: cleared** — user approved treasury variation 0.

**Account state:** PixelLab trial account #6 exhausted (40/40). Registry
reconciles to 120 generations across all accounts. No jobs queued.

## R2b ground tiles (done, live)

7 new tiles (grass + wildflowers/dry/pebbles/thyme variants, agora plaza,
cobblestone road), `create_isometric_tile` block + flat shading, uniform
edge-to-edge prompts. `squash_tile` now extracts only the top-face diamond
(the old one squashed the dirt side faces into the ground); the 4 variants
are colour-matched to the base grass at ingest; roads use the real tile.

## R4 buildings: next is the library — NOT done

Library failed 3x on `create_object_pro_flash` (18 generations): it fills
~98–100% of the canvas for this subject and crops the roof, at 148 and 136,
with "grand" or "small" in the prompt. Treasury only filled 82–90%, so the
fill ratio is per-subject and this tool can't reliably hit a 2×2's
109–134px window.

**Next try:** `create_1_direction_object` at size 168 (4 candidates, ~25
gens). Its measured fill on the treasury at 168 was 122px — squarely in a
2×2's 109–134px window — and 4 candidates give a choice. Needs ≥25 on the
account (the tool pre-checks 25 available).

## R2 complete — everything below is live in production

`tools/art/build_r2_manifest.py` packs every scale-passing asset into
`manifest.production.json` + 3 atlases (`terrain_atlas.png`,
`props_atlas.png`, `buildings_atlas.png`), deployed to
https://projectprometheus-production.up.railway.app with
`NEXT_PUBLIC_SPRITE_SET=production` set on the Railway service.

| Category | What's real | Where it renders |
|---|---|---|
| Buildings | treasury (active phase only) | `render/building.ts` — first real building art |
| Tiles | 5 grass variants, plaza, road | `render/ground.ts` |
| Vegetation | olive_tree ×2, cypress ×2, laurel_bush ×2 | `render/vegetation.ts` |
| Static decor | amphora_pair, column_fragment, tripod_brazier, stone_bench, herm_statue | `render/decor.ts`, sparse (1-in-40 tiles) |

**Treasury finding:** `create_object_pro_flash` (not `create_1_direction_object`)
got it there. 192 canvas → 157px content (81.8% fill, too small); 220 canvas
→ 198px content (passes 163-202px window). `style_image` was attempted but
inline base64 got silently truncated (known MCP limit on large tool args) —
dropped it, the text prompt alone reproduced the approved look on its own
(3rd time in a row with zero style reference). Full detail in STYLE_BIBLE.md.

**Known imperfections, not blocking:**
- Most props still carry a small base/plinth despite the prompt asking for
  none (`style_suffix_prop` reduces it, doesn't eliminate it).
- `road.png` passed scale but has no consumer — `ground.ts` has no atlas
  hook for road tiles, only the default-fill and plaza slots.
- Treasury has only the `active` construction phase; every other phase
  (planned/scaffolding/foundation/damaged/sealed/overgrown) stays procedural.

## R3 (characters) — UNBLOCKED, ready for generations

User decision 2026-09-25: a standing mortal is **~40px tall on a 48px
canvas** (~2/3 of a 64px tile). Encoded in `art/theme.yaml` `scale:` as a
`character` rule measured on content HEIGHT: agents/heroes/townsfolk
48px canvas, 34–44px tall; deities 64px canvas, 46–60px tall. All 30
character keys pass `preflight`. Remember: characters must be created AND
animated on the same account — budget a whole account per batch.

## Deploy gotcha: deploy the WORKTREE explicitly

The Railway CLI link is registered for the MAIN checkout
(`...\Project_Prometheus`). Plain `railway up` from inside this worktree
walks up, finds that link, and uploads the **main checkout's files** —
not the worktree's. Deploys then silently ship whatever is on disk in the
main checkout: "SUCCESS", "Online", and stale art. (An earlier version of
this note blamed a race with GitHub auto-deploy — wrong: a push to main
triggered no deploy at all when checked.) Always deploy with:
```
railway up . --path-as-root --service Project_Prometheus --detach
```
A stale deploy also shows as a suspiciously fast build (just "scheduling
build" in `railway logs --build <id>`).

**After every deploy that matters, verify the actual served file**, not
just deployment status:
```
curl -s <url>/sprites/<atlas>.png -o /tmp/check.png
python -c "from PIL import Image; print(Image.open('/tmp/check.png').size)"
```
compare against the local file's real dimensions. If it doesn't match,
check `railway deployment list --service Project_Prometheus` for a newer
deployment that landed after yours, and redeploy once no other deploy is
in flight.

## On resume
- `get_balance` first.
- Static art (tiles/props/buildings) can live on any account; characters
  must be created AND animated on the same account.
- Download URLs: pixflux `.../mcp/images/{job_id}/download`, iso tile
  `.../mcp/isometric-tile/{id}/download`, 1-direction object
  `.../mcp/objects/{id}/download`, pro-flash object — same objects
  endpoint, check its own response for the exact download field.
  Always `curl -f -A "curl/8.0"`.
- After any new asset passes `check_asset`, add it to `build_r2_manifest.py`'s
  TILES/PROPS/BUILDINGS lists, re-run `python -m tools.art.build_r2_manifest`,
  run both test suites, then redeploy:
  `railway up --service Project_Prometheus --detach`.
- Every job — including rejected/failed-scale ones — is logged in
  `art/registry.json` with `generations_spent`; the running total must
  equal `get_balance`'s `generations_used` after every batch.
