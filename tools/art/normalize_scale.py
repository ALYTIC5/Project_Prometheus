"""A3 - normalise scale across sliced sprites.

Real sequence: slice -> HUMAN names every sprite in art/sliced/overrides.json
-> normalize_scale -> compute_anchors -> build_palette -> pack_atlas ->
verify_atlas. This stage cannot infer a building's FootprintClass without
knowing its kind, and cannot know its kind without a name -- any sprite
still `name: null` is skipped with a warning, and the run fails loudly at
the end listing every skip. That is the intended human checkpoint on a
fresh checkout, not a bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from tools.art.common import (
    ART,
    CLASS_WIDTH,
    KIND_FOOTPRINT,
    alpha_mask,
    footprint_width,
    json_dump,
    load_rgba,
    read_overrides,
    save_rgba,
)

SLICED_DIR = ART / "sliced"
SCALED_DIR = ART / "scaled"

POSTERIZE_BITS = 5
EYE_FRACTION = 0.88
TARGET_EYE_HEIGHT_PX = 34
MIN_HEAD_RUN = 3
TERRAIN_TILE_TARGET_PX = 64
SUSPICIOUS_SCALE_RANGE = (0.25, 4.0)


def _category_of(name: str) -> str:
    if name.startswith(("terrain_", "prop_", "fx_")):
        return name.split("_", 1)[0]
    if name.startswith("monument_tier_"):
        return "building"
    parts = name.split("_")
    if parts[0] in KIND_FOOTPRINT:
        return "building"
    return "agent"


def _building_scale(alpha: np.ndarray, kind: str) -> tuple[float, dict]:
    width = footprint_width(alpha, bottom_frac=0.33)
    footprint_class = KIND_FOOTPRINT[kind]
    scale = CLASS_WIDTH[footprint_class] / width
    return scale, {
        "method": "footprint_width",
        "measured_width": width,
        "footprint_class": footprint_class,
    }


def _character_scale(alpha: np.ndarray) -> tuple[float, dict]:
    ys, _ = np.nonzero(alpha)
    feet_row = int(ys.max())
    head_top = None
    for row in range(int(ys.min()), feet_row + 1):
        run = np.nonzero(alpha[row])[0]
        if len(run) >= MIN_HEAD_RUN:
            head_top = row
            break
    if head_top is None:
        head_top = int(ys.min())
    figure_h = feet_row - head_top
    if figure_h <= 0:
        figure_h = feet_row - int(ys.min()) or 1
    measured_eye_h = figure_h * EYE_FRACTION
    scale = TARGET_EYE_HEIGHT_PX / measured_eye_h
    return scale, {
        "method": "eye_height_heuristic",
        "figure_height": figure_h,
        "measured_eye_height": measured_eye_h,
        "note": "EYE_FRACTION/TARGET_EYE_HEIGHT_PX are a fixed anatomical proxy, not real "
        "eye detection -- stable per-character but not precise; verify cross-role "
        "consistency on art/anchored/contact_sheet.html",
    }


def _terrain_scale(sliced_dir: Path, overrides: dict) -> float:
    """One constant factor for props/terrain/effects, derived from a
    terrain tile's own width against the 64px iso tile target -- these
    must stay proportional to *each other*, not individually normalised."""
    for sprite_id, entry in overrides.items():
        name = entry.get("name")
        if name and name.startswith("terrain_"):
            path = sliced_dir / f"{sprite_id}.png"
            if path.exists():
                alpha = alpha_mask(load_rgba(path))
                if alpha.any():
                    width = footprint_width(alpha, bottom_frac=0.5)
                    if width > 0:
                        return TERRAIN_TILE_TARGET_PX / width
    return 1.0


def _resize_and_posterize(rgba: np.ndarray, scale: float) -> np.ndarray:
    from PIL import Image, ImageOps

    h, w = rgba.shape[:2]
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    img = Image.fromarray(rgba, "RGBA").resize((new_w, new_h), Image.LANCZOS)
    rgb = img.convert("RGB")
    alpha = img.getchannel("A")
    rgb = ImageOps.posterize(rgb, POSTERIZE_BITS)
    # Re-binarise alpha: LANCZOS produces fractional alpha at edges, which
    # would defeat downstream connected-component/anchor logic and leak
    # invisible colours into the palette.
    alpha_arr = np.array(alpha)
    alpha_arr = np.where(alpha_arr >= 128, 255, 0).astype(np.uint8)
    out = np.dstack([np.array(rgb), alpha_arr])
    return out


def main() -> int:
    overrides = read_overrides()
    if not overrides:
        print("No overrides found -- run slice_sheets first", file=sys.stderr)
        return 1

    unnamed = [sid for sid, e in overrides.items() if not e.get("stale") and not e.get("name")]
    named = {sid: e for sid, e in overrides.items() if e.get("name") and e["name"] != "-"}

    terrain_scale = _terrain_scale(SLICED_DIR, overrides)
    SCALED_DIR.mkdir(parents=True, exist_ok=True)

    report_entries = []
    filmstrip_scales: dict[str, float] = {}

    for sprite_id, entry in named.items():
        name = entry["name"]
        src = SLICED_DIR / f"{sprite_id}.png"
        if not src.exists():
            continue
        rgba = load_rgba(src)
        alpha = alpha_mask(rgba)
        if not alpha.any():
            continue

        base_name = name.split("@")[0]
        is_filmstrip = "@" in name
        category = _category_of(base_name)

        if is_filmstrip and base_name in filmstrip_scales:
            scale = filmstrip_scales[base_name]
            method_info = {"method": "shared_filmstrip_scale"}
        elif category == "building":
            kind = base_name.split("_")[0]
            if kind not in KIND_FOOTPRINT:
                kind = "temple"  # monument_tier_* etc fall back to generic footprint
            scale, method_info = _building_scale(alpha, kind)
        elif category == "agent":
            scale, method_info = _character_scale(alpha)
        else:
            scale, method_info = terrain_scale, {"method": "terrain_constant_factor"}

        if is_filmstrip:
            filmstrip_scales[base_name] = scale

        original_size = [int(rgba.shape[1]), int(rgba.shape[0])]
        out = _resize_and_posterize(rgba, scale)
        out_path = SCALED_DIR / f"{name.replace('@', '_f')}.png"
        save_rgba(out, out_path)

        suspicious = not (SUSPICIOUS_SCALE_RANGE[0] <= scale <= SUSPICIOUS_SCALE_RANGE[1])
        report_entries.append(
            {
                "id": sprite_id,
                "name": name,
                "category": category,
                "original_size": original_size,
                "scale_factor": round(scale, 4),
                "final_size": [int(out.shape[1]), int(out.shape[0])],
                "measurement": method_info,
                "suspicious_scale": suspicious,
            }
        )

    json_dump(
        {
            "entries": report_entries,
            "terrain_scale_factor": terrain_scale,
            "skipped_unnamed": unnamed,
        },
        SCALED_DIR / "scale_report.json",
    )

    print(f"Scaled {len(report_entries)} sprites -> {SCALED_DIR}")
    suspicious_count = sum(1 for e in report_entries if e["suspicious_scale"])
    if suspicious_count:
        print(
            f"WARNING: {suspicious_count} sprite(s) have a suspicious scale factor "
            f"outside {SUSPICIOUS_SCALE_RANGE}",
            file=sys.stderr,
        )
    if unnamed:
        print(
            f"WARNING: {len(unnamed)} sprite(s) still unnamed in overrides.json, skipped: "
            f"{', '.join(unnamed[:10])}{'...' if len(unnamed) > 10 else ''}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
