"""A7-verify - read-only checks on the packed atlases + manifest.

Accumulates every failure (no early return) so one run reports everything
wrong at once. Exits 1 on any failure, 0 otherwise.
"""

from __future__ import annotations

import json
import sys

import numpy as np

from tools.art.common import (
    ART_COVERED_KINDS,
    CONSTRUCTION_PHASES,
    SPRITES_DIR,
    ZERO_ART_KINDS,
    load_rgba,
    palette_rgb_list,
)

MAX_MEMORY_BYTES = 40 * 1024 * 1024

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


def main() -> int:
    manifest_path = SPRITES_DIR / "manifest.production.json"
    palette_path = SPRITES_DIR / "sprite_palette.json"
    if not manifest_path.exists():
        print(f"No manifest at {manifest_path} -- run pack_atlas first", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    palette_json = json.loads(palette_path.read_text(encoding="utf-8"))
    palette_set = set(palette_rgb_list(palette_json))

    errors: list[str] = []

    # 1. Coverage: 49 cells resolvable; zero-art kinds have zero entries.
    for kind in ART_COVERED_KINDS:
        for phase in CONSTRUCTION_PHASES:
            key = f"{kind}_{phase}"
            entry = manifest.get(key)
            has_all = entry and entry.get("atlas") and entry.get("frame") and entry.get("anchor")
            if not has_all:
                errors.append(f"coverage: {key} missing atlas/frame/anchor")
    for kind in ZERO_ART_KINDS:
        for phase in CONSTRUCTION_PHASES:
            key = f"{kind}_{phase}"
            if key in manifest:
                errors.append(
                    f"coverage: {key} exists but {kind} is a zero-art kind -- "
                    "this should never have a manifest entry"
                )

    # Load atlases once.
    atlas_images: dict[str, np.ndarray] = {}
    atlas_names = {entry["atlas"] for entry in manifest.values() if entry.get("atlas")}
    for atlas_name in atlas_names:
        path = SPRITES_DIR / atlas_name
        if not path.exists():
            errors.append(f"atlas file missing: {atlas_name}")
            continue
        atlas_images[atlas_name] = load_rgba(path)

    # 2. Palette conformance + alpha binarity.
    for atlas_name, img in atlas_images.items():
        mask = img[:, :, 3] > 0
        rgb = img[:, :, :3][mask]
        if len(rgb):
            unique = np.unique(rgb, axis=0)
            unique_tuples = [tuple(int(v) for v in c) for c in unique]
            bad = [c for c in unique_tuples if c not in palette_set]
            for colour in bad[:20]:
                count = int((rgb == np.array(colour)).all(axis=1).sum())
                errors.append(
                    f"palette: {atlas_name} has colour {colour} ({count}px) outside palette.json"
                )
        alpha = img[:, :, 3]
        non_binary = ((alpha != 0) & (alpha != 255)).sum()
        if non_binary:
            errors.append(f"palette: {atlas_name} has {int(non_binary)} non-binary alpha pixels")

    # 3. Memory budget.
    total_bytes = sum(img.shape[0] * img.shape[1] * 4 for img in atlas_images.values())
    for atlas_name, img in atlas_images.items():
        mb = img.shape[0] * img.shape[1] * 4 / (1024 * 1024)
        print(f"  {atlas_name}: {img.shape[1]}x{img.shape[0]} {mb:.2f} MB")
    if total_bytes > MAX_MEMORY_BYTES:
        errors.append(
            f"memory: total atlas memory {total_bytes / (1024*1024):.2f}MB exceeds "
            f"{MAX_MEMORY_BYTES / (1024*1024):.0f}MB budget"
        )

    # 4/5/7. Anchor bounds, frame bounds, atlas existence.
    for key, entry in manifest.items():
        atlas_name = entry.get("atlas")
        frame = entry.get("frame")
        anchor = entry.get("anchor")
        if not atlas_name or not frame or not anchor:
            continue
        if atlas_name not in atlas_images:
            errors.append(f"frame: {key} references missing atlas {atlas_name}")
            continue
        img = atlas_images[atlas_name]
        atlas_h, atlas_w = img.shape[:2]
        fw, fh = frame["width"], frame["height"]
        frame_count = entry.get("frameCount", 1)
        if frame["x"] < 0 or frame["y"] < 0:
            errors.append(f"frame: {key} has negative frame position")
        if frame["x"] + fw * max(frame_count, 1) > atlas_w:
            errors.append(f"frame: {key} exceeds atlas width ({atlas_name})")
        if frame["y"] + fh > atlas_h:
            errors.append(f"frame: {key} exceeds atlas height ({atlas_name})")
        if not (0 <= anchor["x"] <= fw):
            errors.append(f"anchor: {key} anchor.x={anchor['x']} outside frame width {fw}")
        if not (0 <= anchor["y"] <= fh):
            errors.append(f"anchor: {key} anchor.y={anchor['y']} outside frame height {fh}")

    # 6. Procedural-field agreement for building phase keys.
    for kind in ART_COVERED_KINDS:
        for phase in CONSTRUCTION_PHASES:
            key = f"{kind}_{phase}"
            entry = manifest.get(key)
            if not entry:
                continue
            expected = PROCEDURAL_BY_PHASE[phase]
            for field, value in expected.items():
                if entry.get(field) != value:
                    errors.append(
                        f"procedural: {key}.{field} = {entry.get(field)!r}, "
                        f"expected {value!r} (registry.ts MANIFEST[{phase!r}] mirror)"
                    )

    if errors:
        print("Verification FAILED:")
        for e in errors:
            print(f"  - {e}")
        print(f"{len(errors)} failure(s)")
        return 1

    print(f"total {total_bytes / (1024*1024):.2f} MB / {MAX_MEMORY_BYTES / (1024*1024):.0f} MB")
    real = sum(
        1 for kind in ART_COVERED_KINDS for phase in CONSTRUCTION_PHASES
        if f"{kind}_{phase}" in manifest
    )
    print(f"coverage: {real}/{len(ART_COVERED_KINDS) * len(CONSTRUCTION_PHASES)} cells")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
