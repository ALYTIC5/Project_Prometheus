"""A7-pack - pack scaled, anchored sprites into atlases + manifest.production.json.

Quantises every sprite to palette.json, groups into 5 categories
(buildings/characters/terrain/props/effects), packs each into its own
power-of-two atlas, applies the fallback chain for the 7 art-covered
building kinds x 7 construction phases, and emits
frontend/src/sprites/manifest.production.json matching AtlasSpec exactly.

The fallback rule: sheet 2 (temple/ziggurat) draws generic, silhouette-
agnostic PLANNED/SCAFFOLDING/FOUNDATION art, so any kind missing those
phases borrows temple's. Sheet 2's DAMAGED/SEALED/OVERGROWN are ziggurat-
specific (a cracked ziggurat is not a plausible damaged watchtower), so
late-phase gaps instead fall back to *that same kind's own* ACTIVE frame
-- registry.ts's resolveSprite() already layers the correct procedural
outline (chains/cracks/vines) on top of whatever atlas frame is used, so
this needs zero renderer changes.
"""

from __future__ import annotations

import sys

import numpy as np

from tools.art.common import (
    AGENT_ACTIONS,
    ART,
    ART_COVERED_KINDS,
    CONSTRUCTION_PHASES,
    SPRITES_DIR,
    alpha_mask,
    json_dump,
    load_rgba,
    next_power_of_two,
    palette_rgb_list,
    read_overrides,
    snap_to_palette,
)

SCALED_DIR = ART / "scaled"

CATEGORIES = ("buildings", "characters", "terrain", "props", "effects")
PAD = 2
CANDIDATE_WIDTHS = (256, 512, 1024, 2048, 4096)
DEFAULT_FPS = {"walk": 8, "fx": 6}

REAL = None
# 16 REAL cells, 33 substituted, 49 total. See module docstring for the rule.
FALLBACK: dict[tuple[str, str], str | None] = {
    ("temple", "planned"): REAL,
    ("temple", "scaffolding"): REAL,
    ("temple", "foundation"): REAL,
    ("temple", "active"): REAL,
    ("temple", "damaged"): REAL,
    ("temple", "sealed"): REAL,
    ("temple", "overgrown"): REAL,
    ("monument", "planned"): "temple_planned",
    ("monument", "scaffolding"): "temple_scaffolding",
    ("monument", "foundation"): REAL,  # HUMAN-CONFIRM: "Monument Base" plinth = FOUNDATION
    ("monument", "active"): REAL,
    ("monument", "damaged"): "monument_active",
    ("monument", "sealed"): "monument_active",
    ("monument", "overgrown"): "monument_active",
    ("watchtower", "planned"): "temple_planned",
    ("watchtower", "scaffolding"): "temple_scaffolding",
    ("watchtower", "foundation"): "temple_foundation",
    ("watchtower", "active"): REAL,
    ("watchtower", "damaged"): "watchtower_active",
    ("watchtower", "sealed"): "watchtower_active",
    ("watchtower", "overgrown"): "watchtower_active",
    ("library", "planned"): "temple_planned",
    ("library", "scaffolding"): "temple_scaffolding",
    ("library", "foundation"): "temple_foundation",
    ("library", "active"): REAL,
    ("library", "damaged"): REAL,
    ("library", "sealed"): REAL,  # HUMAN-CONFIRM: "Dormant" stands in for SEALED
    ("library", "overgrown"): "library_active",
    ("forge", "planned"): "temple_planned",
    ("forge", "scaffolding"): "temple_scaffolding",
    ("forge", "foundation"): "temple_foundation",
    ("forge", "active"): REAL,
    ("forge", "damaged"): "forge_active",
    ("forge", "sealed"): "forge_active",
    ("forge", "overgrown"): "forge_active",
    ("arena", "planned"): "temple_planned",
    ("arena", "scaffolding"): "temple_scaffolding",
    ("arena", "foundation"): "temple_foundation",
    ("arena", "active"): REAL,
    ("arena", "damaged"): "arena_active",
    ("arena", "sealed"): "arena_active",
    ("arena", "overgrown"): "arena_active",
    ("oracle", "planned"): "temple_planned",
    ("oracle", "scaffolding"): "temple_scaffolding",
    ("oracle", "foundation"): "temple_foundation",
    ("oracle", "active"): REAL,
    ("oracle", "damaged"): "oracle_active",
    ("oracle", "sealed"): "oracle_active",
    ("oracle", "overgrown"): "oracle_active",
}
HUMAN_CONFIRM_CELLS = {("monument", "foundation"), ("library", "sealed")}

# Mirrors registry.ts's MANIFEST[phase] exactly (frontend/src/sprites/registry.ts).
# resolveSprite() always spreads these AFTER the atlas spec, so the renderer
# ignores what we write here for these 5 fields regardless -- this mirror exists
# so a drift between the two is visible in review, and verify_atlas.py re-asserts it.
PROCEDURAL_BY_PHASE = {
    "planned": {"hasVolume": False, "outline": "dashed-stakes", "outlineColor": 0x888888,
                "litWindows": False, "desaturate": 0.6},
    "scaffolding": {"hasVolume": True, "outline": "post-and-beam", "outlineColor": 0xCCCCCC,
                     "litWindows": False, "desaturate": 0.2},
    "foundation": {"hasVolume": True, "outline": "post-and-beam", "outlineColor": 0xDDDDDD,
                   "litWindows": False, "desaturate": 0.1},
    "active": {"hasVolume": True, "outline": "glow", "outlineColor": 0xFFD700,
               "litWindows": True, "desaturate": 0},
    "damaged": {"hasVolume": True, "outline": "cracks", "outlineColor": 0xFF4444,
                "litWindows": False, "desaturate": 0.1},
    "sealed": {"hasVolume": True, "outline": "chains", "outlineColor": 0xFF0000,
               "litWindows": False, "desaturate": 0.7},
    "overgrown": {"hasVolume": True, "outline": "vines", "outlineColor": 0x3A5F3A,
                  "litWindows": False, "desaturate": 0.5},
}


def _category_of(name: str) -> str:
    if name.startswith("terrain_"):
        return "terrain"
    if name.startswith("prop_"):
        return "props"
    if name.startswith("fx_"):
        return "effects"
    if name.startswith("monument_tier_"):
        return "buildings"
    parts = name.split("_")
    if parts[0] in ART_COVERED_KINDS:
        return "buildings"
    return "characters"


class Sprite:
    __slots__ = ("name", "rgba", "anchor", "fps", "frame_count", "frame_width")

    def __init__(self, name, rgba, anchor, fps, frame_count):
        self.name = name
        self.rgba = rgba
        self.anchor = anchor
        self.fps = fps
        self.frame_count = frame_count
        self.frame_width = rgba.shape[1] // max(frame_count, 1)


def _load_sprites() -> dict[str, Sprite]:
    overrides = read_overrides()
    sprites: dict[str, Sprite] = {}
    for _sprite_id, entry in overrides.items():
        name = entry.get("name")
        if not name or name == "-" or "@" in name:
            continue
        anchor = entry.get("anchor")
        if anchor is None:
            continue
        filename = name
        path = SCALED_DIR / f"{filename}.png"
        if not path.exists():
            continue
        rgba = load_rgba(path)
        sprites[name] = Sprite(
            name, rgba, (round(anchor["x"]), round(anchor["y"])), None, 1
        )

    # Filmstrips: overrides.json name has "@N", scaled file is name_fN.png
    for _sprite_id, entry in overrides.items():
        name = entry.get("name")
        if not name or "@" not in name:
            continue
        base, frame_count_str = name.split("@")
        frame_count = int(frame_count_str)
        filename = f"{base}_f{frame_count}"
        path = SCALED_DIR / f"{filename}.png"
        if not path.exists():
            continue
        anchor = entry.get("anchor") or {"x": 0, "y": 0}
        default_fps = DEFAULT_FPS["fx"] if base.startswith("fx_") else DEFAULT_FPS["walk"]
        fps = entry.get("fps") or default_fps
        rgba = load_rgba(path)
        anchor_xy = (round(anchor["x"]), round(anchor["y"]))
        sprites[base] = Sprite(base, rgba, anchor_xy, fps, frame_count)
    return sprites


def _validate_agent_name(name: str) -> None:
    """Agent names are `{role}_{action}_{f|b}` -- the action segment must
    be one of the 4 legal AgentAction values. A human maps sheet labels
    like "Reading"/"Hammering"/"CarryingScroll" onto these 4 in
    overrides.json; no script infers the mapping, but a typo or an
    unmapped label must fail loudly here rather than silently produce an
    unresolvable manifest key."""
    parts = name.split("_")
    if len(parts) < 2 or parts[1] not in AGENT_ACTIONS:
        print(
            f"FATAL: agent sprite {name!r} has no valid action segment "
            f"(expected one of {AGENT_ACTIONS}) -- fix its name in overrides.json",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _quantize_sprite(rgba: np.ndarray, palette: list[tuple[int, int, int]]) -> np.ndarray:
    out = rgba.copy()
    mask = alpha_mask(rgba)
    memo: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs, strict=False):
        rgb = tuple(int(v) for v in rgba[y, x, :3])
        if rgb not in memo:
            memo[rgb] = snap_to_palette(rgb, palette)
        out[y, x, :3] = memo[rgb]
    out[~mask] = (0, 0, 0, 0)
    return out


def _pack(sprites: list[Sprite]) -> tuple[np.ndarray, dict[str, dict]]:
    ordered = sorted(sprites, key=lambda s: -s.rgba.shape[0])
    best = None
    for max_w in CANDIDATE_WIDTHS:
        x = y = shelf_h = 0
        placements: dict[str, dict] = {}
        overflow = False
        for s in ordered:
            h, w = s.rgba.shape[:2]
            if x + w + PAD > max_w:
                x = 0
                y += shelf_h + PAD
                shelf_h = 0
            if w > max_w:
                overflow = True
                break
            placements[s.name] = {"x": x, "y": y, "width": w, "height": h}
            x += w + PAD
            shelf_h = max(shelf_h, h)
        if overflow:
            continue
        used_w = max((p["x"] + p["width"] for p in placements.values()), default=0)
        used_h = y + shelf_h
        final_w, final_h = next_power_of_two(used_w), next_power_of_two(used_h)
        area = final_w * final_h
        if best is None or area < best[0]:
            best = (area, final_w, final_h, placements)
    if best is None:
        raise ValueError("No candidate atlas width fit all sprites")
    _, final_w, final_h, placements = best
    atlas = np.zeros((final_h, final_w, 4), dtype=np.uint8)
    for s in ordered:
        p = placements[s.name]
        atlas[p["y"] : p["y"] + p["height"], p["x"] : p["x"] + p["width"]] = s.rgba
    return atlas, placements


def main() -> int:
    from PIL import Image

    palette_path = SPRITES_DIR / "palette.json"
    if not palette_path.exists():
        print(f"No palette at {palette_path} -- run build_palette first", file=sys.stderr)
        return 1
    import json

    palette_json = json.loads(palette_path.read_text(encoding="utf-8"))
    palette = palette_rgb_list(palette_json)

    sprites = _load_sprites()
    if not sprites:
        print("No named+anchored sprites found -- run the earlier stages first", file=sys.stderr)
        return 1

    by_category: dict[str, list[Sprite]] = {c: [] for c in CATEGORIES}
    for name, sprite in sprites.items():
        category = _category_of(name)
        if category == "characters":
            _validate_agent_name(name)
        sprite.rgba = _quantize_sprite(sprite.rgba, palette)
        by_category[category].append(sprite)

    manifest: dict[str, dict] = {}
    pack_report: dict = {"categories": {}, "rotation_duplicates": [], "off_schema_extras": []}

    for category, cat_sprites in by_category.items():
        if not cat_sprites:
            continue
        atlas, placements = _pack(cat_sprites)
        atlas_filename = f"{category}_atlas.png"
        Image.fromarray(atlas, "RGBA").save(SPRITES_DIR / atlas_filename)
        pack_report["categories"][category] = {
            "atlas": atlas_filename,
            "size": [int(atlas.shape[1]), int(atlas.shape[0])],
            "sprite_count": len(cat_sprites),
        }
        for s in cat_sprites:
            p = placements[s.name]
            frame_w = p["width"] // max(s.frame_count, 1)
            entry = {
                "hasVolume": True,
                "outline": "none",
                "outlineColor": 0,
                "litWindows": False,
                "desaturate": 0,
                "atlas": atlas_filename,
                "frame": {"x": p["x"], "y": p["y"], "width": frame_w, "height": p["height"]},
                "anchor": {"x": s.anchor[0], "y": s.anchor[1]},
            }
            if s.frame_count > 1:
                entry["frameCount"] = s.frame_count
                entry["fps"] = s.fps

            if category == "characters":
                # {role}_{action}_{f|b} -> {role}_{action}_r{0..7}, front
                # filling r0-r3 and back filling r4-r7 (duplicated, not
                # 8 distinct renders -- resolveAgentSprite() returns null
                # on a miss and this pipeline can't inspect what the
                # renderer does with null, so a duplicated frame is
                # visually imperfect but structurally safe).
                base, facing = s.name.rsplit("_", 1)
                rotations = range(0, 4) if facing == "f" else range(4, 8)
                for r in rotations:
                    key = f"{base}_r{r}"
                    manifest[key] = entry
                    pack_report["rotation_duplicates"].append(key)
            elif category == "buildings":
                phase = s.name.rsplit("_", 1)[-1]
                if phase not in CONSTRUCTION_PHASES:
                    pack_report["off_schema_extras"].append(s.name)
                manifest[s.name] = entry
            else:
                manifest[s.name] = entry

    # Building fallback chain
    coverage_matrix: dict[str, dict] = {}
    for kind in ART_COVERED_KINDS:
        coverage_matrix[kind] = {}
        for phase in CONSTRUCTION_PHASES:
            key = f"{kind}_{phase}"
            fallback_target = FALLBACK.get((kind, phase), REAL)
            if fallback_target is REAL:
                if key not in manifest:
                    print(f"FATAL: {key} marked REAL in FALLBACK but no art found", file=sys.stderr)
                    return 1
                coverage_matrix[kind][phase] = {"status": "real", "key": key}
            else:
                if fallback_target not in manifest:
                    print(
                        f"FATAL: fallback target {fallback_target} for {key} not found",
                        file=sys.stderr,
                    )
                    return 1
                source_entry = manifest[fallback_target]
                procedural = PROCEDURAL_BY_PHASE[phase]
                manifest[key] = {
                    **procedural,
                    "atlas": source_entry["atlas"],
                    "frame": source_entry["frame"],
                    "anchor": source_entry["anchor"],
                }
                coverage_matrix[kind][phase] = {
                    "status": "substituted",
                    "key": key,
                    "source": fallback_target,
                }
        # Overwrite the 5 procedural fields on REAL cells too, to mirror registry.ts
        for phase in CONSTRUCTION_PHASES:
            key = f"{kind}_{phase}"
            if key in manifest:
                manifest[key].update(PROCEDURAL_BY_PHASE[phase])

    coverage_matrix["_zero_art_kinds_note"] = (
        "harbour/vault/treasury/archive/underworld intentionally have zero manifest "
        "entries and render procedurally -- absence is correct, not a gap"
    )

    json_dump(manifest, SPRITES_DIR / "manifest.production.json")
    json_dump(coverage_matrix, ART / "coverage_matrix.json")
    pack_report["renderer_contract_assumptions"] = (
        "Animation strips: manifest 'frame' is frame-0's rect (width = one frame's "
        "width); the renderer is assumed to read frameCount contiguous frames of that "
        "width starting there. Unverified from this side -- render/*.ts is off-limits."
    )
    pack_report["human_confirm_cells"] = sorted(f"{k}_{p}" for k, p in HUMAN_CONFIRM_CELLS)
    json_dump(pack_report, ART / "pack_report.json")

    real_count = sum(
        1 for kind in ART_COVERED_KINDS for phase in CONSTRUCTION_PHASES
        if coverage_matrix[kind][phase]["status"] == "real"
    )
    total_cells = len(ART_COVERED_KINDS) * len(CONSTRUCTION_PHASES)
    print(f"Manifest: {len(manifest)} keys")
    print(f"Coverage: {real_count}/{total_cells} real, {total_cells - real_count} substituted")
    print(f"HUMAN-CONFIRM cells: {pack_report['human_confirm_cells']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
