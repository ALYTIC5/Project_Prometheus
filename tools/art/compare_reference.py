"""A8 - measure a screenshot's tonal range against the approved art direction.

Numbers, not vibes. Computes brightness (Rec.709 luminance) median/p90, HSV
saturation median, and frame-occupied % (share of pixels that aren't
background) from a screenshot PNG, and prints them against the approved
targets. Run after every tonal-range change.

Reports BOTH full-frame and city-only (background-masked) numbers. With frame
occupancy still well under 100% (the map-resize/fit-to-bounds work is a
separate, later effort), empty background pixels arithmetically cap the
full-frame median no matter how bright the city itself is -- masking it out
is honest measurement, not a way to inflate the number.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from tools.art.common import ART, json_dump, load_rgba

# The approved art-direction targets (measured against art/reference/want.png).
TARGETS = {
    "brightness_median": 0.41,
    "brightness_p90": 0.61,
    "saturation_median": 0.25,
    "frame_occupied_pct": 100.0,
}

# frontend/src/components/WorldView.tsx's CANVAS_BG -- pixels within
# BACKGROUND_TOLERANCE of this are "empty frame", not "city".
DEFAULT_BACKGROUND = (0x1C, 0x24, 0x38)
BACKGROUND_TOLERANCE = 24.0


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """Rec.709 luminance per pixel, rgb as float array in [0, 1], shape (N, 3)."""
    return rgb[:, 0] * 0.2126 + rgb[:, 1] * 0.7152 + rgb[:, 2] * 0.0722


def _saturation(rgb: np.ndarray) -> np.ndarray:
    """HSV saturation per pixel, rgb as float array in [0, 1], shape (N, 3)."""
    channel_max = rgb.max(axis=1)
    channel_min = rgb.min(axis=1)
    sat = np.zeros_like(channel_max)
    nonzero = channel_max > 0
    sat[nonzero] = (channel_max[nonzero] - channel_min[nonzero]) / channel_max[nonzero]
    return sat


def _background_mask(
    rgb_u8: np.ndarray, background: tuple[int, int, int], tolerance: float
) -> np.ndarray:
    dist = np.linalg.norm(rgb_u8.astype(np.float64) - np.array(background), axis=1)
    return dist <= tolerance


def compute_metrics(
    image: np.ndarray,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
    tolerance: float = BACKGROUND_TOLERANCE,
) -> dict:
    rgb_u8 = image[:, :, :3].reshape(-1, 3)
    rgb = rgb_u8.astype(np.float64) / 255.0

    lum = _luminance(rgb)
    sat = _saturation(rgb)

    is_bg = _background_mask(rgb_u8, background, tolerance)
    is_city = ~is_bg
    frame_occupied_pct = float(is_city.mean() * 100.0)

    def _summary(values: np.ndarray) -> dict:
        if len(values) == 0:
            return {"median": 0.0, "p90": 0.0}
        return {"median": float(np.median(values)), "p90": float(np.percentile(values, 90))}

    return {
        "full_frame": {
            "brightness": _summary(lum),
            "saturation_median": float(np.median(sat)),
        },
        "city_only": {
            "brightness": _summary(lum[is_city]),
            "saturation_median": float(np.median(sat[is_city])) if is_city.any() else 0.0,
            "pixel_count": int(is_city.sum()),
        },
        "frame_occupied_pct": frame_occupied_pct,
    }


def _print_report(name: str, metrics: dict) -> None:
    ff = metrics["full_frame"]
    city = metrics["city_only"]
    print(f"\n{name}")
    print(f"{'metric':<22}{'full-frame':<14}{'city-only':<14}{'target':<10}")
    print(
        f"{'brightness median':<22}{ff['brightness']['median']:<14.3f}"
        f"{city['brightness']['median']:<14.3f}{TARGETS['brightness_median']:<10}"
    )
    print(
        f"{'brightness p90':<22}{ff['brightness']['p90']:<14.3f}"
        f"{city['brightness']['p90']:<14.3f}{TARGETS['brightness_p90']:<10}"
    )
    print(
        f"{'saturation median':<22}{ff['saturation_median']:<14.3f}"
        f"{city['saturation_median']:<14.3f}{TARGETS['saturation_median']:<10}"
    )
    print(
        f"{'frame occupied %':<22}{metrics['frame_occupied_pct']:<14.1f}"
        f"{'':<14}{TARGETS['frame_occupied_pct']:<10}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path, help="PNG screenshot of the rendered world")
    parser.add_argument(
        "--target", type=Path, default=None, help="Optional want.png to compare against directly"
    )
    parser.add_argument(
        "--background",
        type=str,
        default=None,
        help="Background hex colour to mask out (default: WorldView.tsx's CANVAS_BG)",
    )
    args = parser.parse_args()

    if not args.screenshot.exists():
        print(f"No screenshot at {args.screenshot}", file=sys.stderr)
        return 1

    background = DEFAULT_BACKGROUND
    if args.background:
        h = args.background.lstrip("#")
        background = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    current = compute_metrics(load_rgba(args.screenshot), background)
    _print_report(f"current ({args.screenshot.name})", current)

    report = {"current": current}

    if args.target:
        if not args.target.exists():
            print(f"No target image at {args.target}", file=sys.stderr)
            return 1
        target_metrics = compute_metrics(load_rgba(args.target), background)
        _print_report(f"target ({args.target.name})", target_metrics)
        report["target"] = target_metrics

    json_dump(report, ART / "tone_report.json")

    ff = current["full_frame"]
    passing = (
        ff["brightness"]["median"] > TARGETS["brightness_median"] * 0.85
        and ff["brightness"]["p90"] > TARGETS["brightness_p90"] * 0.85
    )
    print(f"\n{'PASS' if passing else 'below target'} -- see {ART / 'tone_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
