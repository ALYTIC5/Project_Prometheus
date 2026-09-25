# RESUME — Greek Rebuild

**Prompt pack:** Greek Rebuild R0–R12. **R2 (style anchor) is DONE.**
**HUMAN GATE 1: cleared** — user approved treasury variation 0.

**Account state:** PixelLab trial account #6, 15/40 spent, 25 remaining.
No jobs queued or running.

## R2 complete — everything below is live in production

`tools/art/build_r2_manifest.py` packs every scale-passing asset into
`manifest.production.json` + 3 atlases (`terrain_atlas.png`,
`props_atlas.png`, `buildings_atlas.png`), deployed to
https://projectprometheus-production.up.railway.app with
`NEXT_PUBLIC_SPRITE_SET=production` set on the Railway service.

| Category | What's real | Where it renders |
|---|---|---|
| Buildings | treasury (active phase only) | `render/building.ts` — first real building art |
| Tiles | grass, plaza | `render/ground.ts` |
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

## Next: R3 (characters) — needs a decision, not just generations

Before generating ANY character: character canvas/height has **no scale
rule** in `art/theme.yaml` yet, and `tools/art/scale.py`'s `preflight()`
refuses generation for `deities`/`agents`/`heroes`/`townsfolk` until one
exists. Ask the user: how tall should a character be, relative to the
64px tile? Then add a `scale.categories` entry for each character category
before spending any generations on R3.

## Deploy gotcha (hit and fixed this session)

Railway's `Project_Prometheus` service is connected to GitHub and
**auto-deploys on every push to `main`**, independent of `railway up`.
Every `git push origin HEAD:main` triggers its own build, racing the
manual `railway up` deploy. If an OLDER push's auto-deploy is slow and
finishes AFTER a newer manual deploy, it silently overwrites it with
stale content — this happened here: the treasury atlas deployed fine,
then got silently replaced by a delayed auto-deploy of an earlier commit
that predated it, serving the old 512×1024 medieval `buildings_atlas.png`
for several minutes despite `railway status` showing "Online" throughout.

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
