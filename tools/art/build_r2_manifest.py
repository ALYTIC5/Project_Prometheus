"""R2 world wiring: pack the scale-passing Greek assets into real atlases
and manifest.production.json, so the live renderer shows them instead of
procedural placeholders (registry.ts's resolveTerrainSprite/resolvePropSprite).

Scope, deliberately: only assets that PASS `tools/art/check_asset.py` (law
W11 + T3) are ingested. The treasury (still fails scale) and the 5 static
props with no placement call site yet (amphora_pair, column_fragment,
tripod_brazier, stone_bench, herm_statue) ARE packed into props_atlas.png
and given manifest keys -- "what you have" should be usable the moment a
render/*.ts call site wants it -- but nothing in render/*.ts references
them yet; only vegetation.ts's tree/bush slots are wired (see
frontend/src/world/render/vegetation.ts).

Reuses tools/art/pack_atlas.py's `_pack` shelf-packing algorithm (not
duplicated) and common.py's `anchor_prop`. Skips the quantization step
pack_atlas.py applies to old medieval-JPEG-recovered art: this is clean
PixelLab RGBA, the same case pack_atlas.py itself already carves out for
characters_atlas.png.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from tools.art.common import (
    PUBLIC_SPRITES_DIR,
    SPRITES_DIR,
    alpha_mask,
    anchor_building,
    anchor_prop,
    bbox_of,
    json_dump,
)
from tools.art.pack_atlas import Sprite, _pack

TILE_TARGET = (64, 32)  # projection.ts TILE_WIDTH x TILE_HEIGHT

# (manifest key, source file) -- every tile has its top-face diamond
# extracted by squash_tile. Keys match render/ground.ts's lookups.
TILES = [
    ("terrain_grass", Path("art/raw/tiles/grass_v2.png")),
    ("terrain_grass_flowers", Path("art/raw/tiles/grass_flowers.png")),
    ("terrain_grass_dry", Path("art/raw/tiles/grass_dry.png")),
    ("terrain_grass_pebbles", Path("art/raw/tiles/grass_pebbles.png")),
    ("terrain_grass_thyme", Path("art/raw/tiles/grass_thyme.png")),
    ("terrain_cobblestone", Path("art/raw/tiles/plaza_v2.png")),
    ("terrain_road", Path("art/raw/tiles/road_v2.png")),
]
# Ground-fill variants get colour-matched to this one (see match_colour) so
# a hash-scattered mix reads as one field. Plaza and road are deliberately
# different surfaces and keep their own colour.
TILE_COLOUR_REFERENCE = "terrain_grass"
TILE_COLOUR_MATCHED = {
    "terrain_grass_flowers", "terrain_grass_dry", "terrain_grass_pebbles", "terrain_grass_thyme",
}

# (manifest base name, [source files in variant order]) -- keys become
# prop_<name>_<index>. Every entry here already passed check_asset --key.
PROPS: list[tuple[str, list[Path]]] = [
    ("olive_tree", [Path("art/raw/props/olive_tree.png"), Path("art/raw/props/olive_tree_v2.png")]),
    ("cypress", [Path("art/raw/props/cypress.png"), Path("art/raw/props/cypress_v3.png")]),
    ("laurel_bush", [Path("art/raw/props/laurel_bush.png"),
                     Path("art/raw/props/laurel_bush_v2.png")]),
    ("amphora_pair", [Path("art/raw/props/amphora_pair.png")]),
    ("column_fragment", [Path("art/raw/props/column_fragment.png")]),
    ("tripod_brazier", [Path("art/raw/props/tripod_brazier.png")]),
    ("stone_bench", [Path("art/raw/props/stone_bench.png")]),
    ("herm_statue", [Path("art/raw/props/herm_statue.png")]),
]

# (kind, construction phase, source file) -- manifest key becomes
# {kind}_{phase}, matching registry.ts's resolveSprite() lookup exactly.
# Only 'active' exists for treasury so far: every other phase (planned,
# scaffolding, foundation, damaged, sealed, overgrown) has no manifest
# entry and stays procedural, same graceful-null precedent as everything
# else here. This OVERWRITES the old stale medieval buildings_atlas.png
# (orphaned since R0 deleted manifest.production.json) with real Greek art.
BUILDINGS: list[tuple[str, str, Path]] = [
    ("treasury", "active", Path("art/raw/buildings/treasury_final_220.png")),
]

# Mirrors registry.ts's MANIFEST[phase] exactly -- resolveSprite() spreads
# these over the atlas spec regardless, so this is for manifest-file
# self-consistency (and any future reviewer), not functional. Extend this
# dict, not a single hardcoded value, if BUILDINGS grows more phases.
PROCEDURAL_BY_PHASE = {
    "planned": {"hasVolume": False, "outline": "dashed-stakes", "outlineColor": 0x888888,
                "litWindows": False, "desaturate": 0.6},
    "active": {"hasVolume": True, "outline": "glow", "outlineColor": 0xFFD700,
               "litWindows": True, "desaturate": 0},
}


def squash_tile(rgba: np.ndarray, target: tuple[int, int] = TILE_TARGET) -> np.ndarray:
    """Extract ONLY the top-face diamond of a PixelLab iso tile, then
    NEAREST-resize it to `target` (width, height).

    create_isometric_tile returns a block: a top-face diamond above side
    faces (dirt/stone thickness). The top face runs from the first opaque
    row down to the equator (the first full-width row) and mirrors below
    it; everything under that is side face and must not reach the ground
    plane -- an earlier version cropped the whole opaque bbox and squashed
    the sides INTO the top face, putting a brown band in every tile. The
    face's aspect ratio is also never the requested 2:1 (measured 64x36,
    64x38, 64x28 across shapes) -- the resize fixes that at ingest."""
    mask = alpha_mask(rgba)
    if not mask.any():
        raise ValueError("squash_tile: empty tile")
    x0, y0, x1, y1 = bbox_of(mask)
    full_width = x1 - x0 + 1
    row_widths = mask[:, x0 : x1 + 1].sum(axis=1)
    full_rows = np.nonzero(row_widths >= full_width)[0]
    equator = int(full_rows[0])
    # Measure the face's half-height from the BOTTOM "V" (last full-width
    # row down to the bottom tip), not from the top: grass blades poking
    # above the diamond push the first opaque row up and made an earlier
    # version over-measure the face and include the side band.
    half_h = max(1, y1 - int(full_rows[-1]))
    face_top = max(y0, equator - half_h)
    face_bottom = min(y1, equator + half_h)
    face = rgba[face_top : face_bottom + 1, x0 : x1 + 1].copy()

    # Keep only pixels inside the diamond; anything outside is side face
    # (below the equator) or background.
    h, w = face.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2, float(equator - face_top)
    inside = (np.abs(xs - cx) / (w / 2) + np.abs(ys - cy) / (half_h + 0.5)) <= 1.0
    face[~inside] = 0

    img = Image.fromarray(face, "RGBA").resize(target, Image.NEAREST)
    out = np.array(img)
    # Re-mask at the target size so the diamond edge is exact (NEAREST can
    # leave stray corner pixels) and fill any hole inside it from neighbours.
    th, tw = out.shape[:2]
    ys, xs = np.mgrid[0:th, 0:tw]
    diamond = (np.abs(xs + 0.5 - tw / 2) / (tw / 2) + np.abs(ys + 0.5 - th / 2) / (th / 2)) <= 1.0
    out[~diamond] = 0
    for _ in range(4):  # a few passes cover the 1-2px edge gaps the resize leaves
        holes = diamond & (out[:, :, 3] == 0)
        if not holes.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            src = np.roll(out, (dy, dx), axis=(0, 1))
            fill = holes & (src[:, :, 3] > 0)
            out[fill] = src[fill]
            holes &= ~fill
    return out


def match_colour(rgba: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Shift `rgba`'s opaque pixels to `reference`'s per-channel mean and
    spread (mean/std transfer), keeping its own texture and detail.

    Ground variants are generated one at a time and come back in clearly
    different hues (R2b: lime, olive, saturated gold); scattered across the
    map by hash, that reads as a patchwork, not one field. Matching every
    variant to the base grass keeps the variety in texture and small
    features (flowers, pebbles) while making neighbours read as the same
    ground."""
    out = rgba.copy()
    mask = rgba[:, :, 3] > 0
    ref_mask = reference[:, :, 3] > 0
    src = rgba[mask][:, :3].astype(np.float64)
    ref = reference[ref_mask][:, :3].astype(np.float64)
    src_std = src.std(axis=0)
    src_std[src_std == 0] = 1.0
    matched = (src - src.mean(axis=0)) / src_std * ref.std(axis=0) + ref.mean(axis=0)
    out_rgb = out[:, :, :3]
    out_rgb[mask] = np.clip(np.rint(matched), 0, 255).astype(np.uint8)
    return out


def _load_tile_sprites() -> list[Sprite]:
    faces = {name: squash_tile(np.array(Image.open(path).convert("RGBA"))) for name, path in TILES}
    reference = faces[TILE_COLOUR_REFERENCE]
    sprites = []
    for name, _path in TILES:
        face = match_colour(faces[name], reference) if name in TILE_COLOUR_MATCHED else faces[name]
        # Ground-tile anchor = canvas centre: ground.ts positions the sprite
        # at the diamond's centre point (gridToScreen), same convention as
        # its own procedural diamond poly.
        w, h = TILE_TARGET
        sprites.append(Sprite(name, face, (w // 2, h // 2), None, 1))
    return sprites


def _load_prop_sprites() -> list[Sprite]:
    sprites = []
    for base_name, paths in PROPS:
        for index, path in enumerate(paths):
            rgba = np.array(Image.open(path).convert("RGBA"))
            mask = alpha_mask(rgba)
            ax, ay = anchor_prop(mask)
            name = f"prop_{base_name}_{index}"
            sprites.append(Sprite(name, rgba, (round(ax), round(ay)), None, 1))
    return sprites


def _load_building_sprites() -> list[Sprite]:
    sprites = []
    for kind, phase, path in BUILDINGS:
        rgba = np.array(Image.open(path).convert("RGBA"))
        mask = alpha_mask(rgba)
        ax, ay = anchor_building(mask)
        sprites.append(Sprite(f"{kind}_{phase}", rgba, (round(ax), round(ay)), None, 1))
    return sprites


def _write_atlas(sprites: list[Sprite], atlas_filename: str) -> dict[str, dict]:
    atlas, placements = _pack(sprites)
    PUBLIC_SPRITES_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(atlas, "RGBA").save(PUBLIC_SPRITES_DIR / atlas_filename)
    manifest: dict[str, dict] = {}
    for s in sprites:
        p = placements[s.name]
        manifest[s.name] = {
            "hasVolume": True,
            "outline": "none",
            "outlineColor": 0,
            "litWindows": False,
            "desaturate": 0,
            "atlas": atlas_filename,
            "frame": {"x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"]},
            "anchor": {"x": s.anchor[0], "y": s.anchor[1]},
        }
    return manifest


def main() -> int:
    tile_sprites = _load_tile_sprites()
    prop_sprites = _load_prop_sprites()
    building_sprites = _load_building_sprites()

    manifest: dict[str, dict] = {}
    manifest.update(_write_atlas(tile_sprites, "terrain_atlas.png"))
    manifest.update(_write_atlas(prop_sprites, "props_atlas.png"))
    manifest.update(_write_atlas(building_sprites, "buildings_atlas.png"))
    for kind, phase, _path in BUILDINGS:
        manifest[f"{kind}_{phase}"].update(PROCEDURAL_BY_PHASE[phase])

    manifest_path = SPRITES_DIR / "manifest.production.json"
    json_dump(manifest, manifest_path)
    print(f"Wrote {manifest_path}: {len(manifest)} keys")
    print(f"  tiles: {[s.name for s in tile_sprites]}")
    print(f"  props: {[s.name for s in prop_sprites]}")
    print(f"  buildings: {[s.name for s in building_sprites]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
