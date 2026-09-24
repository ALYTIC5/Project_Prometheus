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
- **World scale (1 tile = 64 px wide):** 2×2 building ≈ 128 px content
  width (treasury anchor: 122 ✓). Props must stay well under one tile:
  small props (amphora, bench, brazier, herm) ≤ ~24 px wide, trees ≤ ~32 px
  wide. Generate props on a 32 px canvas, not 64. The R2 64 px props (content
  34–60 px wide) are ~2× too large and must not ship as-is. Check the
  content bounding box, not just the canvas, before ingesting any asset.

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

*(R2 has not yet run. This section is filled in once a style anchor is
generated and approved — see the Greek Rebuild prompt pack's own R2 gate.)*
