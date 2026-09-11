"""A1 - recover real alpha from the nine JPEG concept-art sheets.

Mockups/BATCH 0{1-9}.jpg carry a checkerboard convention for intended
transparency (no real alpha channel, JPEG ringing smeared onto every
sprite edge) plus, on some sheets, solid reference/comparison panels that
are layout chrome, not sprite background. This produces art/recovered/
batch_0N.png (RGBA) + a report per sheet, and flags anything ambiguous to
art/review/ for a human to look at instead of guessing.

Known limitation, by design rather than oversight: sheets with soft drop
shadows blended under a tile darken the checkerboard locally, shifting
those pixels away from the sheet's two globally-sampled greys. The default
tolerance (22) is a reasonable middle ground (measured against
Mockups/BATCH 01.jpg: tighter values leave more shadow speckle *and* start
rejecting genuine checker pixels, looser values clean the shadow speckle
but start eating thin dark linework and even title-bar text) -- there is
no single global tolerance that is simultaneously perfect on every sheet.
`--tolerance` exists so a human can retune per sheet after reviewing the
magenta-composited output, rather than this script silently guessing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from tools.art.common import (
    ART,
    MOCKUPS,
    classify_checkerboard,
    detect_checkerboard,
    fill_small_holes,
    json_dump,
    label_components,
    local_std_windows,
    majority_filter_3x3,
    remove_small_opaque_specks,
    repair_ring_colours,
    rgb_to_hex,
    strip_frame_components,
)

RECOVERED_DIR = ART / "recovered"
REVIEW_DIR = ART / "review"

SOLID_STD_MAX = 3.0
SOLID_MIN_AREA = 40_000
SOLID_BORDERLINE_MIN_AREA = 15_000
SOLID_FILL_RATIO_REAL = 0.85
SOLID_FILL_RATIO_BORDERLINE = 0.70
HOLE_MAX_AREA = 64
SPECK_MAX_AREA = 20


def _solid_panels(rgb: np.ndarray, period: int) -> tuple[list[dict], list[dict]]:
    """Distinguish 'a big uniform rectangle' from checkerboard by local
    variance, not colour -- checkerboard's local std is roughly half the
    two greys' delta (tens of levels); a solid panel's is near zero. The
    separation is large enough that this needs no per-sheet tuning."""
    gray = rgb.mean(axis=2)
    window = max(4 * period, 32)
    stride = max(period, 8)
    std_grid = local_std_windows(gray, window=window, stride=stride)
    solid_mask = std_grid < SOLID_STD_MAX

    # Expand the coarse grid mask back to full resolution for connected
    # component labelling of contiguous solid regions.
    full_mask = np.zeros(rgb.shape[:2], dtype=bool)
    gh, gw = solid_mask.shape
    for j in range(gh):
        for i in range(gw):
            if solid_mask[j, i]:
                y0, x0 = j * stride, i * stride
                full_mask[y0 : y0 + window, x0 : x0 + window] = True

    labels, n = label_components(full_mask)
    discarded: list[dict] = []
    borderline: list[dict] = []
    for label_id in range(1, n + 1):
        region = labels == label_id
        area = int(region.sum())
        ys, xs = np.nonzero(region)
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        bbox_area = (y1 - y0 + 1) * (x1 - x0 + 1)
        fill_ratio = area / bbox_area if bbox_area else 0.0
        entry = {"bbox": [x0, y0, x1 + 1, y1 + 1], "area": area, "fill_ratio": round(fill_ratio, 3)}
        if area >= SOLID_MIN_AREA and fill_ratio >= SOLID_FILL_RATIO_REAL:
            discarded.append(entry)
        elif area >= SOLID_BORDERLINE_MIN_AREA and fill_ratio >= SOLID_FILL_RATIO_BORDERLINE:
            borderline.append(entry)
    return discarded, borderline


def recover_sheet(path: Path, tolerance: float = 22.0, strip_frame: bool = True) -> dict:
    from PIL import Image

    img = Image.open(path).convert("RGB")
    rgb = np.array(img)
    h, w = rgb.shape[:2]

    report_checker = detect_checkerboard(rgb)
    is_checker = classify_checkerboard(rgb, report_checker, tolerance=tolerance)
    is_checker = majority_filter_3x3(is_checker)

    discarded_panels, borderline_panels = _solid_panels(rgb, report_checker.period)
    for panel in discarded_panels:
        x0, y0, x1, y1 = panel["bbox"]
        is_checker[y0:y1, x0:x1] = True

    hole_fills_before = is_checker.sum()
    is_checker = fill_small_holes(is_checker, max_hole_area=HOLE_MAX_AREA)
    hole_fills = int(hole_fills_before - is_checker.sum())

    opaque = ~is_checker
    opaque_before_speck_removal = int(opaque.sum())
    opaque = remove_small_opaque_specks(opaque, max_speck_area=SPECK_MAX_AREA)
    speck_removals = opaque_before_speck_removal - int(opaque.sum())

    # Only ever auto-removes a component small enough to plausibly BE a
    # header/border/divider line (see strip_frame_components' docstring --
    # this project's own sheet 2 had 170k+ px of REQUIRED temple art
    # matching the same bbox/fill-ratio shape as real chrome, which an
    # earlier, unguarded version of this step silently deleted). Anything
    # matching the shape but too large to be chrome is left alone and
    # dumped to art/review/ instead of guessed at either way.
    frame_boxes: list[tuple[int, int, int, int]] = []
    ambiguous_frame_boxes: list[tuple[int, int, int, int]] = []
    if strip_frame:
        opaque, frame_boxes, ambiguous_frame_boxes = strip_frame_components(opaque)

    repaired_rgb, repaired_count, unresolved_count = repair_ring_colours(rgb, opaque)

    alpha = np.where(opaque, 255, 0).astype(np.uint8)
    rgba = np.dstack([repaired_rgb, alpha])

    labels, n_regions = label_components(opaque)
    regions = []
    for label_id in range(1, n_regions + 1):
        region = labels == label_id
        area = int(region.sum())
        if area == 0:
            continue
        ys, xs = np.nonzero(region)
        regions.append(
            {
                "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
                "opaque_px": area,
            }
        )

    review_flags = []
    RECOVERED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    stem = path.stem.lower().replace(" ", "_")

    if not report_checker.ok:
        review_path = REVIEW_DIR / f"{stem}_low_confidence.png"
        Image.fromarray(rgba, "RGBA").save(review_path)
        review_flags.append({"file": str(review_path), "reason": "low_confidence_checkerboard"})

    for idx, panel in enumerate(discarded_panels):
        x0, y0, x1, y1 = panel["bbox"]
        crop = Image.fromarray(rgb[y0:y1, x0:x1], "RGB")
        review_path = REVIEW_DIR / f"{stem}_panel_{idx}.png"
        crop.save(review_path)
        review_flags.append({"file": str(review_path), "reason": "solid_panel_discarded"})

    for idx, panel in enumerate(borderline_panels):
        x0, y0, x1, y1 = panel["bbox"]
        crop = Image.fromarray(rgb[y0:y1, x0:x1], "RGB")
        review_path = REVIEW_DIR / f"{stem}_borderline_{idx}.png"
        crop.save(review_path)
        review_flags.append({"file": str(review_path), "reason": "borderline_solid_region"})

    for idx, box in enumerate(ambiguous_frame_boxes):
        x0, y0, x1, y1 = box
        crop = Image.fromarray(rgb[y0:y1, x0:x1], "RGB")
        review_path = REVIEW_DIR / f"{stem}_ambiguous_frame_{idx}.png"
        crop.save(review_path)
        review_flags.append(
            {
                "file": str(review_path),
                "reason": "ambiguous_frame_shaped_but_too_large_to_auto_strip",
            }
        )

    out_path = RECOVERED_DIR / f"{stem}.png"
    Image.fromarray(rgba, "RGBA").save(out_path)

    report = {
        "source": str(path.relative_to(path.parents[1])),
        "size": [w, h],
        "tolerance": tolerance,
        "checkerboard": {
            "period": report_checker.period,
            "grey_a": rgb_to_hex(report_checker.grey_a),
            "grey_b": rgb_to_hex(report_checker.grey_b),
            "confidence": round(report_checker.confidence, 3),
            "method": report_checker.method,
        },
        "pixels": {
            "total": h * w,
            "made_transparent": int((~opaque).sum()),
            "recoloured_by_ring_repair": repaired_count,
            "hole_fills": hole_fills,
            "speck_removals": speck_removals,
            "unresolved_ring_pixels": unresolved_count,
        },
        "discarded_panels": discarded_panels,
        "stripped_frame_boxes": frame_boxes,
        "ambiguous_frame_boxes": ambiguous_frame_boxes,
        "regions_are_coarse": True,
        "regions": regions,
        "review_flags": review_flags,
    }
    json_dump(report, RECOVERED_DIR / f"{stem}.report.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sheet", help="Only process this one sheet filename (e.g. 'BATCH 04.jpg')"
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=22.0,
        help="Colour-distance tolerance for checker classification (default 22; retune per "
        "sheet after reviewing the magenta-composited output -- see module docstring).",
    )
    parser.add_argument(
        "--no-strip-frame",
        action="store_true",
        help="Disable border/frame/divider chrome removal. It strips a whole connected "
        "component, which can delete real content that touches the frame line (see "
        "recover_sheet's docstring) -- disable per-sheet if review shows a loss like that.",
    )
    args = parser.parse_args()

    sheets = sorted(MOCKUPS.glob("BATCH *.jpg"))
    if args.sheet:
        sheets = [s for s in sheets if s.name == args.sheet]
    if not sheets:
        print(f"No sheets found in {MOCKUPS}", file=sys.stderr)
        return 1
    for sheet in sheets:
        report = recover_sheet(sheet, tolerance=args.tolerance, strip_frame=not args.no_strip_frame)
        print(
            f"{sheet.name}: period={report['checkerboard']['period']} "
            f"confidence={report['checkerboard']['confidence']} "
            f"transparent={report['pixels']['made_transparent']}/{report['pixels']['total']} "
            f"panels_discarded={len(report['discarded_panels'])} "
            f"review_flags={len(report['review_flags'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
