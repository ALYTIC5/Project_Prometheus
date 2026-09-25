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

# (registry key, source file, PixelLab-generated top-face height we measured)
TILES = [
    ("terrain_grass", Path("art/raw/tiles/grass_calibration.png")),
    ("terrain_cobblestone", Path("art/raw/tiles/plaza.png")),
]

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
    """Crop to the opaque top-face's own bounding box, then NEAREST-resize
    to `target` (width, height). PixelLab's create_isometric_tile never
    returns the requested aspect ratio (measured 64x36/64x38/64x41 across
    block/thick/thin shape requests, target is 64x32 -- see STYLE_BIBLE.md
    "canvas-to-content fill ratio" finding) -- this is the documented fix,
    applied at ingest so no further generation is needed."""
    mask = alpha_mask(rgba)
    if not mask.any():
        raise ValueError("squash_tile: empty tile")
    x0, y0, x1, y1 = bbox_of(mask)
    cropped = rgba[y0 : y1 + 1, x0 : x1 + 1]
    img = Image.fromarray(cropped, "RGBA").resize(target, Image.NEAREST)
    return np.array(img)


def _load_tile_sprites() -> list[Sprite]:
    sprites = []
    for name, path in TILES:
        rgba = np.array(Image.open(path).convert("RGBA"))
        squashed = squash_tile(rgba)
        # Ground-tile anchor = canvas centre: ground.ts positions the sprite
        # at the diamond's centre point (gridToScreen), same convention as
        # its own procedural diamond poly.
        w, h = TILE_TARGET
        sprites.append(Sprite(name, squashed, (w // 2, h // 2), None, 1))
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
