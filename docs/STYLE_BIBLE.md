# Style Bible — Greek Rebuild

**Text-only style authority.** `want.png` and `QuantPantheonConcept.jpg`
(the Greek doc's originally-intended style images) do not exist anywhere in
this repository and were never generated — by explicit user decision
(2026-09-24), this rebuild proceeds on text descriptions alone
(`art/theme.yaml` + `art/prompts.yaml`, enforced by `tools/art/prompt_lint.py`)
rather than image-anchored generation. If real reference images are supplied
later, R2 (style anchor) should be re-run with `style_images` added to its
`create_1_direction_object`/`create_character` calls, and this file updated.

## Projection and scale

- Projection: 2:1 isometric. Tile top face 64×32 native px (matches
  `frontend/src/world/iso/projection.ts`'s existing convention — verify
  against that file, not re-derived here).
- Characters: 48×48 requested canvas (deities: 64×64 requested). **PixelLab's
  `size` parameter has never once returned its requested value across three
  prior sessions** (48→68, 68→96, 68→96 again) — always confirm the actual
  size via `tools/art/check_asset.py` after every generation, never assume
  the request was honored.
- Buildings: canvas 168px for 2×2 and 3×3 footprints, 256px for 4×4
  landmarks (Oracle of Delphi, The Amphitheatre, Temple of Mnemosyne).
- Backend footprint truth: `tools/art/common.py`'s `KIND_FOOTPRINT` maps
  building `kind` to a `TOWER`/`MEDIUM`/`LARGE` pixel-width class, verified
  against `prometheus/world/construction.py`'s real `BUILDING_LOCATIONS`.
  `art/theme.yaml`'s own `footprint: [w, h]` field is in TILE units (for
  world-layout purposes, R6) — the two are different unit systems for
  different consumers, not a conflict.
- Tile calibration (R2, `create_isometric_tile`, trial account, 1 gen,
  job `86311d90`): requested 64 → canvas 64×64, measured top face **64×36**
  (target 64×32). The trial-available tile tool has no view-angle
  parameter (`create_tiles_pro` needs a paid Tier 1 plan). Fix is local:
  nearest-neighbour vertical squash of the top face 36→32 at ingest, never
  a re-generation. Tiles are checked with `check_asset --tile` (edge contact
  is expected for a full-width tile, not clipping).
- `tile_shape` does NOT control top-face height (measured, same prompt, 64px):
  block 64×36, thin 64×28, thick 64×38. The ingest squash (to 32) is
  therefore the fix for every tile, whatever shape is requested.
- Props (R2): `create_image_pixflux` (1 gen, isometric, forced palette =
  anchor + grass colours) gives on-style props, drawn on small plinth/
  ground bases. Prompts that mention marble surfaces (amphora_pair,
  column_fragment) come back as whole scenes or buildings: the world
  style suffix's "terracotta roof tiles" pulls them there. Props need their
  own style suffix without roof tiles before those two are re-run.
- **World scale (law W11, enforced by `tools/art/scale.py`; numbers in
  `art/theme.yaml` `scale:`):** 1 tile = 64 px wide. Building content width =
  (w+h)×32 px from the BACKEND footprint (`construction.py`
  BUILDING_LOCATIONS): 1×1 = 64, 2×2 = 128, 3×3 = 192 (allowed 85–105%).
  theme.yaml's own `footprint` fields disagree with the backend (library,
  oracle, watchtower) and are NOT used for sizing. A 3×3 building does not
  fit a 168 canvas: use 256 -- but see the finding below before assuming
  that works. Props: 32 px canvas WIDTH is fixed; canvas HEIGHT must be
  taller than width for upright props (trees/bushes/pillars) via
  `scale.prop_canvas(key)` -- a square canvas crops their top/bottom.
  Content ≤24 px wide by default; two deliberate per-key overrides exist
  (stone_bench, tripod_brazier → 28 px) because their natural shape is
  wider than tall, verified against the rendered result, not raised to
  dodge a failure. Characters: no rule yet → generation refused until
  decided.
- **`create_1_direction_object`'s canvas-to-content fill ratio is NOT
  linear or predictable.** R2 measured: 168 px canvas → 122 px content
  (73% fill); 256 px canvas → 239 px content (93% fill, now TOO WIDE for
  the 192 px 3×3 footprint). Two points don't determine the curve --
  do not pick a third canvas size by interpolating. Use
  `create_object_pro_flash` instead for buildings needing a specific
  content width: it accepts a custom canvas AND a `style_image` (lock the
  Gate-1-approved look via `treasury_anchor_c0` or whichever variation was
  picked) and its cost is a flat, quotable tier (`get_pro_flash_capabilities`
  is a free lookup) rather than create_1_direction_object's 20–40 guess --
  180 and 192 px canvases both quoted 6 generations; 96 px quoted 5 but is
  too small for a 3×3 footprint's ~192 px target. Iterate canvas size
  against `check_asset --key treasury` within a small budget.
- R2 scale results: treasury anchor v1 (168 canvas) 122 px wide, v2 (256
  canvas, `create_1_direction_object`) 239 px wide -- both **FAIL** the
  163–202 px window for a 3×3 footprint (an earlier note here wrongly
  called v1 correct against a 2×2). All 8 props now PASS after two rounds
  of correction (canvas height for upright props, tighter framing/deliberate
  width overrides for the rest). Road, grass and plaza tiles pass.
- **Treasury v3 (`create_object_pro_flash`, no style_image) PASSES**: 192
  canvas → 157 px content (81.8% fill, too small); 220 canvas → 198 px
  content (**inside 163-202**, shipped). `style_image` was attempted first
  but the inline base64 payload was silently truncated in transit (a known
  MCP/LLM-client limit on large tool arguments -- prefer a hosted URL over
  inline base64 for anything much above icon-sized, when one is available).
  Dropped it and relied on the text prompt alone, which had already
  reproduced the same approved look twice (v1, v2) with zero style
  reference -- this tool's fill ratio (81.8% at 192) is its own curve,
  not comparable to `create_1_direction_object`'s (73%/93%).

## Camera and light

- Default zoom 2×, integer zoom levels at rest, fractional only during
  camera flights (see `frontend/src/world/render/camera.ts`).
- Light from the top-left (already the renderer's convention).
- Dark, crisp outlines. Contact shadows are engine-drawn, never baked into
  sprite art.

## Palette

No image exists to sample a palette from. `frontend/src/world/sprites/palette.json`
already holds a hand-authored 8-family semantic palette
(`stone/blue/orange/purple/yellow/green/red/slate`, 4 shades each) that
predates this rebuild and is **not** image-derived — it's generic enough to
serve the Greek theme without changes. Greek meaning mapping (documentation
only, hex values unchanged):

| Family | Hex range | Greek meaning |
|---|---|---|
| `stone` | `#77644C`–`#DED5CB` | marble, limestone, unpainted stone |
| `blue` | `#3070A5`–`#BADBF7` | Aegean water, sky |
| `orange` | `#AD5917`–`#FAD0AE` | terracotta roof tiles, sun-baked earth |
| `purple` | `#954FBB`–`#E4CFF0` | crystal accents, divine/mystical glow |
| `yellow` | `#816709`–`#F8D862` | bronze, gold-leaf, laurel |
| `green` | `#1C7F46`–`#A2E8BF` | olive and cypress greenery |
| `red` | `#D6493B`–`#FACDC9` | fire, hearth glow, alarm states |
| `slate` | `#294156`–`#88A8C5` | shadow, void background, night |

If real Greek reference art is supplied later, re-run palette derivation
against it and update this table (and `sprite_palette.json`, previously
image-sampled and deleted in the R0 reset since its medieval-art source no
longer exists).

## Building-kind vocabulary (existing renderer keys)

`frontend/src/world/sprites/registry.ts`'s `SILHOUETTE`/`STOREYS` maps use
these `kind` keys already; `art/theme.yaml`'s `buildings` table uses the same
keys so generated art plugs into the existing (simple, flat-lookup) manifest
without renderer changes: `library`, `forge`, `harbour`, `watchtower`,
`vault`, `arena`, `treasury`, `archive`, `underworld`, `temple`, `monument`.
Five new kinds from the Greek world bible — `evolution_lab`,
`temple_of_knowledge`, `observatory`, `hall_of_legends`, `machine_temple` —
have `theme.yaml` entries but **no registry.ts entry yet**; wiring them into
`SILHOUETTE`/`STOREYS` is R4/R6 work, not R1's.

## Mood

Bright, sunlit Mediterranean by day. No specific "world composition" (island,
forest border, bay) is locked yet since it was originally meant to be derived
from `want.png` — R6 (assemble the world) defines the actual layout in
`world_client/map/layout.json` from the building list and its own judgment,
not from an image that doesn't exist.

## Approved anchor

**HUMAN GATE 1: cleared.** Variation 0 (clean white marble, terracotta roof,
gold pediment) approved by the user — `art/raw/buildings/treasury_anchor_c0.png`.
This is the STYLE reference: palette and look for every later asset derive
from it (see "World scale" above for why the shipped treasury still needs a
larger re-render before it's usable in-world).

## World wiring (R2 -> live renderer)

`tools/art/build_r2_manifest.py` packs every scale-passing R2 asset into real
atlases and `frontend/src/world/sprites/manifest.production.json`:

- **Tiles** (`terrain_atlas.png`): `terrain_grass`, `terrain_cobblestone`.
  Each tile is squashed at ingest (crop to opaque bbox, NEAREST resize to
  64×32) — the fix for the canvas-to-content mismatch noted above; no
  further generation needed for this.
- **Props** (`props_atlas.png`): all 8 R2 props, keyed `prop_<name>_<variant>`
  (olive_tree/cypress/laurel_bush have 2 variants each; the other 5 have 1).
  Anchor = bottom-centre of each sprite's own opaque bbox
  (`tools/art/common.py`'s `anchor_prop`).
- **Wired into the live renderer:** `render/vegetation.ts`'s tree/bush scatter
  now draws real olive_tree/cypress/laurel_bush art (in `SPRITE_SET=production`)
  instead of procedural PixiJS shapes, picked by an independent deterministic
  hash per tile — falls back to the original procedural draw on any miss.
  A "dead" (Underworld-zone) tree always stays procedural: there is no
  bare/withered real art, and that's a deliberate visual distinction, not a
  gap to paper over.
- **Packed but NOT yet placed:** amphora_pair, column_fragment,
  tripod_brazier, stone_bench, herm_statue. They're in `props_atlas.png` and
  the manifest, ready for `resolvePropSprite`, but no render call site
  scatters them yet — that's a future decor-placement step, not done here.
- **Fixed two latent bugs found while wiring this up:** `tools/art/common.py`'s
  `SPRITES_DIR` pointed at a directory that no longer exists
  (`frontend/src/sprites` → `frontend/src/world/sprites`), and
  `atlasTextures.ts` had no per-atlas error handling, so one missing atlas
  file would have broken the entire renderer instead of falling back to
  procedural for just that category.
- **To see it:** run the frontend with `NEXT_PUBLIC_SPRITE_SET=production`.
  Treasury/building art is NOT part of this manifest yet (still fails scale
  — see above), so buildings keep rendering procedurally regardless.
