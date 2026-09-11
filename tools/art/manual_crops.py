"""Manual crops for sprites connected-component slicing genuinely cannot
separate: zero pixel gap in the source art at these locations (confirmed
via morphological opening tests up to radius 6 with no separation --
these renders are drawn touching their neighbours or the panel border
directly, not merely close to them). slice_sheets.py correctly leaves
this content intact as one "frame_like" sprite covering the whole sheet
(see its module docstring); this script crops the individually-identified
regions out of that sheet-sized sprite by hand-determined bounding box,
using visual inspection against Mockups/BATCH 0N.jpg.

Coordinates are approximate (determined by eye against each sheet's
layout, not measured to the pixel) and will need occasional touch-up --
that is expected, not a bug; retune CROPS below and rerun. This is the
"if a human can provide cleaner source separation, that beats any
recovery heuristic" case the rest of this pipeline's docstrings mention,
just applied at the slicing stage instead of A1.

Run after slice_sheets.py, before normalize_scale.py. Idempotent: an
entry already present in sprites.json is skipped, not re-cropped.
"""

from __future__ import annotations

import json

from PIL import Image

from tools.art.common import ART

SLICED = ART / "sliced"

# (source frame_like sprite id, crop box in sheet-absolute pixel coords,
#  new sprite id, final name)
CROPS = [
    ("batch_01_r03_c00", (0, 540, 283, 768), "batch_01_manual_beach", "terrain_beach"),
    ("batch_01_r03_c00", (283, 540, 566, 768), "batch_01_manual_dock", "terrain_dock"),
    ("batch_01_r03_c00", (566, 540, 850, 768), "batch_01_manual_cliff", "terrain_cliff"),
    ("batch_02_r04_c00", (0, 455, 280, 748), "batch_02_manual_damaged", "temple_damaged"),
    ("batch_02_r04_c00", (290, 420, 560, 748), "batch_02_manual_sealed", "temple_sealed"),
    ("batch_02_r04_c00", (568, 420, 840, 748), "batch_02_manual_overgrown", "temple_overgrown"),
    # "Monument Base" (the plinth) stands in for FOUNDATION -- HUMAN-CONFIRM
    # cell in pack_atlas.py's FALLBACK dict; flip to monument_tier_base if
    # a human reviewing art/anchored/contact_sheet.html disagrees.
    ("batch_04_r02_c00", (0, 40, 190, 280), "batch_04_manual_base", "monument_foundation"),
    ("batch_04_r02_c00", (340, 40, 560, 280), "batch_04_manual_short", "monument_tier_short"),
    ("batch_04_r02_c00", (868, 40, 1060, 390), "batch_04_manual_tall", "monument_tier_tall"),
    ("batch_04_r02_c00", (1210, 40, 1408, 745), "batch_04_manual_extreme", "monument_tier_extreme"),
    ("batch_05_r04_c00", (0, 40, 310, 745), "batch_05_manual_active", "watchtower_active"),
    ("batch_06_r05_c00", (0, 40, 545, 420), "batch_06_manual_active", "library_active"),
    ("batch_06_r05_c00", (0, 460, 310, 745), "batch_06_manual_damaged", "library_damaged"),
    # "Dormant Library" stands in for SEALED -- the other HUMAN-CONFIRM cell.
    ("batch_06_r05_c00", (310, 460, 560, 745), "batch_06_manual_dormant", "library_sealed"),
    ("batch_07_r05_c00", (0, 40, 710, 720), "batch_07_manual_active", "forge_active"),
    ("batch_08_r06_c00", (0, 40, 590, 490), "batch_08_manual_active", "arena_active"),
    ("batch_09_r02_c00", (0, 30, 615, 720), "batch_09_manual_active", "oracle_active"),
]


def main() -> None:
    sprites_path = SLICED / "sprites.json"
    overrides_path = SLICED / "overrides.json"
    sprites_data = json.loads(sprites_path.read_text(encoding="utf-8"))
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))

    existing_ids = {s["id"] for s in sprites_data["sprites"]}
    added = 0
    for source_id, box, new_id, name in CROPS:
        if new_id in existing_ids:
            print(f"skip (exists): {new_id}")
            continue
        src_path = SLICED / f"{source_id}.png"
        img = Image.open(src_path).convert("RGBA")
        crop = img.crop(box)
        out_path = SLICED / f"{new_id}.png"
        crop.save(out_path)

        alpha = crop.getchannel("A")
        opaque_px = sum(1 for v in alpha.getdata() if v > 0)
        sheet = source_id.rsplit("_r", 1)[0]
        sprites_data["sprites"].append(
            {
                "id": new_id,
                "sheet": sheet,
                "file": str((SLICED / f"{new_id}.png").relative_to(ART.parent)).replace(
                    "\\", "/"
                ),
                "bbox": list(box),
                "size": [box[2] - box[0], box[3] - box[1]],
                "opaque_px": opaque_px,
                "components_merged": 0,
                "frame_like": False,
                "manual_crop": True,
                "manual_crop_source": source_id,
            }
        )
        overrides[new_id] = {"name": name, "anchor": None, "notes": "manual crop"}
        added += 1
        print(f"added: {new_id} -> {name} {box}")

    sprites_data["sprites"].sort(key=lambda s: s["id"])
    sprites_path.write_text(
        json.dumps(sprites_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    overrides_path.write_text(
        json.dumps(overrides, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"\nAdded {added} manual crops.")


if __name__ == "__main__":
    main()
