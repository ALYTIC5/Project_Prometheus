"""A2 - slice recovered sheets into individual sprites.

Connected-component labelling on the recovered alpha, merged by bbox gap
(a torch's flame separated from its post must rejoin), produces one PNG
per surviving sprite plus a contact sheet for human review and the
overrides.json a human names every sprite through -- see
tools/art/README.md for the naming convention.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from tools.art.common import (
    ART,
    Box,
    bbox_of,
    json_dump,
    label_components,
    load_rgba,
    merge_boxes_by_gap,
    write_overrides_merge,
)

RECOVERED_DIR = ART / "recovered"
SLICED_DIR = ART / "sliced"

DEFAULT_MERGE_GAP = 6.0
# Character filmstrip sheets: adjacent walk/action frames sit close
# together and must NOT merge into one blob -- a tighter gap here.
PER_SHEET_MERGE_GAP = {
    "batch_03": 3.0,
    "batch_06": 3.0,
    "batch_07": 3.0,
    "batch_08": 3.0,
}
MIN_AREA = 120
MIN_DIMENSION = 6
# Same shape-only signature as recover_alpha's strip_frame_components, but
# used here to EXCLUDE a frame/border/divider-shaped component from
# gap-based merging entirely, never to delete its pixels. A single such
# component's bbox spans a huge fraction of the sheet, so
# merge_boxes_by_gap's bbox-to-bbox distance reads as ~0 to nearly every
# other component regardless of gap threshold -- confirmed: this alone
# (independent of whether the component's pixels are ever deleted) was
# enough to re-fuse an entire sheet into one "sprite". Keeping the
# component's own pixels intact as its own unmerged group means no art is
# ever lost -- only excluded from acting as a bridge.
FRAME_BBOX_AREA_FRAC = 0.15
FRAME_MAX_FILL_RATIO = 0.6


def _row_band_index(centres_y: list[float]) -> list[int]:
    """Cluster sprite centre-y into row bands: a new band starts when the
    gap to the previous sorted centre exceeds half the median sprite
    height-proxy (here, half the median gap between consecutive sorted
    centres would degenerate on uniform rows, so use half the overall
    spread's typical step instead: the median absolute gap)."""
    order = sorted(range(len(centres_y)), key=lambda i: centres_y[i])
    if not order:
        return []
    gaps = [centres_y[order[i]] - centres_y[order[i - 1]] for i in range(1, len(order))]
    threshold = (sorted(gaps)[len(gaps) // 2] if gaps else 0) * 2 + 1e-6
    bands = [0] * len(centres_y)
    band = 0
    for i in range(1, len(order)):
        if centres_y[order[i]] - centres_y[order[i - 1]] > max(threshold, 20):
            band += 1
        bands[order[i]] = band
    return bands


def slice_sheet(recovered_path: Path, merge_gap: float) -> list[dict]:
    from PIL import Image

    rgba = load_rgba(recovered_path)
    alpha = rgba[:, :, 3] > 0
    labels, n = label_components(alpha)
    if n == 0:
        return []

    boxes: list[Box] = []
    areas: list[int] = []
    for label_id in range(1, n + 1):
        region = labels == label_id
        x0, y0, x1, y1 = bbox_of(region)
        boxes.append((x0, y0, x1, y1))
        areas.append(int(region.sum()))

    sheet_area = alpha.shape[0] * alpha.shape[1]
    frame_like: set[int] = set()
    for i, (x0, y0, x1, y1) in enumerate(boxes):
        bbox_area = (x1 - x0 + 1) * (y1 - y0 + 1)
        fill_ratio = areas[i] / bbox_area if bbox_area else 0.0
        if bbox_area >= FRAME_BBOX_AREA_FRAC * sheet_area and fill_ratio <= FRAME_MAX_FILL_RATIO:
            frame_like.add(i)

    mergeable_idx = [i for i in range(len(boxes)) if i not in frame_like]
    mergeable_boxes = [boxes[i] for i in mergeable_idx]
    mergeable_groups = merge_boxes_by_gap(mergeable_boxes, gap=merge_gap)
    groups = [[mergeable_idx[i] for i in group] for group in mergeable_groups]
    groups.extend([i] for i in sorted(frame_like))

    sheet_stem = recovered_path.stem
    sprites = []
    rejected_count = 0
    rejected_area = 0
    accepted: list[tuple[Box, int, np.ndarray, bool]] = []
    for group in groups:
        group_boxes = [boxes[i] for i in group]
        x0 = min(b[0] for b in group_boxes)
        y0 = min(b[1] for b in group_boxes)
        x1 = max(b[2] for b in group_boxes)
        y1 = max(b[3] for b in group_boxes)
        crop_alpha = alpha[y0 : y1 + 1, x0 : x1 + 1]
        opaque_px = int(crop_alpha.sum())
        width, height = x1 - x0 + 1, y1 - y0 + 1
        if opaque_px < MIN_AREA or width < MIN_DIMENSION or height < MIN_DIMENSION:
            rejected_count += 1
            rejected_area += opaque_px
            continue
        cy = (y0 + y1) / 2.0
        is_frame_like = len(group) == 1 and group[0] in frame_like
        accepted.append(((x0, y0, x1, y1), len(group), np.array([cy]), is_frame_like))

    centres_y = [float(a[2][0]) for a in accepted]
    bands = _row_band_index(centres_y)
    order_in_band: dict[int, list[int]] = {}
    for idx, band in enumerate(bands):
        order_in_band.setdefault(band, []).append(idx)

    SLICED_DIR.mkdir(parents=True, exist_ok=True)
    for band, indices in order_in_band.items():
        indices.sort(key=lambda i: accepted[i][0][0])
        for col, idx in enumerate(indices):
            (x0, y0, x1, y1), n_merged, _, is_frame_like = accepted[idx]
            sprite_id = f"{sheet_stem}_r{band:02d}_c{col:02d}"
            crop = rgba[y0 : y1 + 1, x0 : x1 + 1]
            out_path = SLICED_DIR / f"{sprite_id}.png"
            Image.fromarray(crop, "RGBA").save(out_path)
            sprites.append(
                {
                    "id": sprite_id,
                    "sheet": sheet_stem,
                    "file": str(out_path.relative_to(ART.parent)),
                    "bbox": [x0, y0, x1 + 1, y1 + 1],
                    "size": [x1 - x0 + 1, y1 - y0 + 1],
                    "opaque_px": int(rgba[y0 : y1 + 1, x0 : x1 + 1, 3].astype(bool).sum()),
                    "components_merged": n_merged,
                    "frame_like": is_frame_like,
                }
            )

    sprites.sort(key=lambda s: s["id"])
    print(
        f"{sheet_stem}: {len(sprites)} sprites, {rejected_count} rejected "
        f"({rejected_area}px total)"
    )
    return sprites


def _write_contact_sheet(all_sprites: list[dict]) -> None:
    rows = []
    for sprite in all_sprites:
        rel = Path(sprite["file"]).name
        w, h = sprite["size"]
        rows.append(
            f'<figure><img src="{rel}" alt="{sprite["id"]}">'
            f'<figcaption>{sprite["id"]} &middot; {w}x{h}</figcaption></figure>'
        )
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sliced sprites contact sheet</title>
<style>
body {{ background: #222; color: #eee; font-family: sans-serif; margin: 0; padding: 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, 140px); gap: 8px; }}
figure {{
  margin: 0; padding: 8px; background:
    repeating-conic-gradient(#444 0% 25%, #333 0% 50%) 0 0 / 16px 16px;
  border: 1px solid #555; text-align: center;
}}
img {{ max-width: 120px; max-height: 120px; display: block; margin: 0 auto; }}
figcaption {{ font-size: 10px; margin-top: 4px; word-break: break-all; }}
</style></head>
<body>
<h1>Sliced sprites ({len(all_sprites)})</h1>
<div class="grid">
{"".join(rows)}
</div>
</body></html>
"""
    (SLICED_DIR / "contact_sheet.html").write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sheets",
        help="Comma-separated sheet stems to process (e.g. 'batch_01,batch_02'). "
        "Default: every recovered sheet in art/recovered/.",
    )
    args = parser.parse_args()

    sheets = sorted(RECOVERED_DIR.glob("batch_*.png"))
    if args.sheets:
        wanted = {s.strip() for s in args.sheets.split(",")}
        sheets = [s for s in sheets if s.stem in wanted]
    if not sheets:
        print(f"No recovered sheets in {RECOVERED_DIR} -- run recover_alpha first", file=sys.stderr)
        return 1

    all_sprites: list[dict] = []
    for sheet in sheets:
        merge_gap = PER_SHEET_MERGE_GAP.get(sheet.stem, DEFAULT_MERGE_GAP)
        all_sprites.extend(slice_sheet(sheet, merge_gap))

    SLICED_DIR.mkdir(parents=True, exist_ok=True)
    json_dump(
        {
            "generated_from": [str(s) for s in sheets],
            "params": {"default_merge_gap": DEFAULT_MERGE_GAP, "per_sheet": PER_SHEET_MERGE_GAP},
            "sprites": all_sprites,
        },
        SLICED_DIR / "sprites.json",
    )
    _write_contact_sheet(all_sprites)
    write_overrides_merge([s["id"] for s in all_sprites])

    print(f"Total: {len(all_sprites)} sprites sliced.")
    print(f"Review: {SLICED_DIR / 'contact_sheet.html'}")
    print(f"Name every sprite in: {SLICED_DIR / 'overrides.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
