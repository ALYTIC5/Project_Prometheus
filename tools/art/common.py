"""Shared, disk-free helpers for the tools/art/ concept-art -> atlas pipeline.

Every function here is pure (no filesystem access besides the explicit
load/save wrappers and the overrides.json accessors) so tests/test_art_*.py
can exercise the algorithms on synthetic arrays without touching Mockups/
or writing image files.
"""

from __future__ import annotations

import colorsys
import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCKUPS = REPO_ROOT / "Mockups"
ART = REPO_ROOT / "art"
SPRITES_DIR = REPO_ROOT / "frontend" / "src" / "sprites"

# Canonical footprint pixel widths tied to the tile system (registry.ts's
# FootprintClass). TOWER's height is unconstrained by design.
CLASS_WIDTH = {"TOWER": 64, "MEDIUM": 128, "LARGE": 192}

# Verified against prometheus/world/construction.py:118-130
# BUILDING_LOCATIONS -- the backend's real footprint, not a guess.
KIND_FOOTPRINT = {
    "monument": "TOWER",
    "watchtower": "TOWER",
    "forge": "LARGE",
    "oracle": "LARGE",
    "arena": "LARGE",
    "library": "MEDIUM",
    "temple": "MEDIUM",
}

CONSTRUCTION_PHASES = [
    "planned",
    "scaffolding",
    "foundation",
    "active",
    "damaged",
    "sealed",
    "overgrown",
]
ART_COVERED_KINDS = ["temple", "monument", "watchtower", "library", "forge", "arena", "oracle"]
ZERO_ART_KINDS = ["harbour", "vault", "treasury", "archive", "underworld"]
AGENT_ROLES_WITH_ART = ["builder", "scribe", "engineer", "experimenter"]
AGENT_ACTIONS = ["idle", "walk", "work", "carry"]

OVERRIDES_PATH = ART / "sliced" / "overrides.json"


# --------------------------------------------------------------------------
# Image I/O
# --------------------------------------------------------------------------


def load_rgba(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"))


def save_rgba(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA").save(path)


def alpha_mask(arr: np.ndarray) -> np.ndarray:
    return arr[:, :, 3] > 0


def bbox_of(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        raise ValueError("bbox_of called on an empty mask")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def colour_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.dist(a, b)


def json_dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def next_power_of_two(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


# --------------------------------------------------------------------------
# A1 - checkerboard detection
# --------------------------------------------------------------------------

MIN_PERIOD = 4
MAX_PERIOD = 64
AUTOCORR_CONFIDENCE_MIN = 0.5
HARMONIC_CONFIDENCE_MIN = 0.5
WINDOW_LEN = 192  # >= 3 * MAX_PERIOD so even the largest allowed tile still
# shows a full harmonic-doubling cycle within one window (see
# _is_true_checkerboard_window).
WINDOW_ROW_STRIDE = 24
WINDOW_COL_STRIDE = 48
MIN_VOTES = 5
MIN_GREY_DELTA = 12
MAX_SATURATION = 12


@dataclass
class CheckerReport:
    period: int
    grey_a: tuple[int, int, int]
    grey_b: tuple[int, int, int]
    confidence: float
    method: str
    ok: bool
    # Every distinct high-amplitude (grey_a, grey_b) pair found across the
    # sheet, deduped. Sheets that lay out multiple side-by-side reference
    # panels sometimes render each panel's checkerboard at a slightly
    # different tone (confirmed on Mockups/BATCH 01.jpg: the terrain-tile
    # panel's checker is measurably darker/lower-contrast than the props
    # panel's) -- a single global pair then correctly classifies one panel
    # and leaves the other almost entirely opaque. `classify_checkerboard`
    # checks every pair and takes the best match, so this generalises to
    # multi-panel sheets without needing an explicit panel-segmentation
    # step. `grey_a`/`grey_b` above stay the single highest-amplitude pair,
    # kept for the report and for sheets where only one pair exists.
    colour_pairs: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = field(
        default_factory=list
    )


def _normalized_autocorr(line: np.ndarray) -> np.ndarray | None:
    """Zero-lag-normalized autocorrelation of a 1-D scanline, or None for
    a constant line. Computed once per window and reused by both the
    period pick and the harmonic-doubling check in
    `_window_period_and_validity` -- `np.correlate` is the expensive part
    here and this is called once per sheet per window.
    """
    x = line.astype(np.float64) - line.mean()
    if x.std() < 1e-6:
        return None
    ac = np.correlate(x, x, mode="full")[len(x) - 1 :]
    denom = ac[0] if ac[0] > 1e-9 else 1e-9
    return ac / denom


def _window_period_and_validity(line: np.ndarray) -> tuple[int, float, bool, float]:
    """One autocorrelation pass per window, feeding both the period pick
    and the validity check below (`np.correlate` is the expensive part;
    computing it twice per window roughly doubled A1's runtime for no
    benefit).

    Validity requires two things beyond a confident period:

    1. Harmonic doubling: a real checkerboard's autocorrelation doesn't
       just have one strong lag -- it *doubles back up* near +1 at 2x
       that lag (the full cycle), because the signal really is a
       periodic square wave. Incidental edges from painted art content
       produce a single strong-ish correlation at some short lag without
       this harmonic signature, which is what let a handful of
       dense-artwork windows on real sheets outvote the genuine, much
       larger, background windows for the wrong (too-small) period in
       practice -- confirmed against Mockups/BATCH 01.jpg.
    2. Amplitude: that harmonic check alone still isn't enough -- real
       JPEG sheets also carry a genuinely periodic ~4px luminance ripple
       (chroma-subsampling / dithering, not noise) that passes the
       harmonic test with a very high repeat count in a long window, at
       a much smaller amplitude than an intentional transparency grid.
       Requiring the window's own even/odd luminance delta to clear
       MIN_GREY_DELTA is what actually separates "designed high-contrast
       grid" from "incidental low-amplitude periodic compression
       texture" (measured delta means of ~3 vs ~18 on the same sheet's
       period-4 vs period-6 candidate windows).
    """
    ac = _normalized_autocorr(line)
    if ac is None:
        return MIN_PERIOD, 0.0, False, 0.0
    hi = min(MAX_PERIOD, len(ac) - 1)
    if hi <= MIN_PERIOD:
        return MIN_PERIOD, 0.0, False, 0.0
    window = ac[MIN_PERIOD : hi + 1]
    best_idx = int(np.argmax(np.abs(window)))
    period = best_idx + MIN_PERIOD
    confidence = float(abs(window[best_idx]))

    if confidence < AUTOCORR_CONFIDENCE_MIN:
        return period, confidence, False, 0.0
    harmonic_lag = 2 * period
    if harmonic_lag >= len(ac):
        return period, confidence, False, 0.0
    if ac[harmonic_lag] < HARMONIC_CONFIDENCE_MIN:
        return period, confidence, False, 0.0
    idx = np.arange(len(line))
    even = (idx // period) % 2 == 0
    delta = abs(float(line[even].mean()) - float(line[~even].mean()))
    return period, confidence, delta >= MIN_GREY_DELTA, delta


def detect_checkerboard(rgb: np.ndarray) -> CheckerReport:
    """Empirically detect a sheet's checkerboard period + two grey values.

    Never hardcode a period/colour -- different sheets use different
    checkerboard scales. A hand-painted concept sheet is mostly *not* bare
    background (dense artwork covers much of the frame), so a handful of
    long scanlines is unreliable -- one crossing busy art can out-vote the
    truth. Instead this samples many short WINDOW_LEN windows across the
    whole sheet, keeps only windows whose autocorrelation has the true
    checkerboard's harmonic-doubling + amplitude signature (see
    `_window_period_and_validity`), and takes the modal period among
    those.

    The two greys are sampled from the highest-*amplitude* matching
    window, not the highest-*confidence* one: confidence measures how
    cleanly periodic a window is, which a softly shadow-darkened patch of
    real checkerboard can still score highly on even though its absolute
    contrast is reduced. Picking such a window as the colour reference
    then makes the *rest* of the sheet's full-contrast checker pixels fail
    the tolerance test against these muted greys -- confirmed on
    Mockups/BATCH 01.jpg, where the highest-confidence window sampled
    (202,239) (delta 37) while the sheet's prevailing checker colours were
    actually (185,255) (delta 70), and classifying against the former left
    roughly half of every checker cell (and, via 8-connectivity, most of
    the sheet) still marked opaque. The highest-*amplitude* window is the
    least degraded example of the same two colours and generalises far
    better across the sheet.
    """
    h, w = rgb.shape[:2]
    gray = rgb.mean(axis=2)

    # (period, confidence, axis, index, start, delta)
    votes: list[tuple[int, float, str, int, int, float]] = []
    for y in range(0, max(1, h - WINDOW_LEN), WINDOW_ROW_STRIDE):
        for x0 in range(0, max(1, w - WINDOW_LEN), WINDOW_COL_STRIDE):
            seg = gray[y, x0 : x0 + WINDOW_LEN]
            p, c, valid, delta = _window_period_and_validity(seg)
            if valid:
                votes.append((p, c, "row", y, x0, delta))
    for x in range(0, max(1, w - WINDOW_LEN), WINDOW_ROW_STRIDE):
        for y0 in range(0, max(1, h - WINDOW_LEN), WINDOW_COL_STRIDE):
            seg = gray[y0 : y0 + WINDOW_LEN, x]
            p, c, valid, delta = _window_period_and_validity(seg)
            if valid:
                votes.append((p, c, "col", x, y0, delta))

    if len(votes) < MIN_VOTES:
        return _histogram_fallback(rgb)

    periods = [v[0] for v in votes]
    period = max(set(periods), key=periods.count)
    matching = [v for v in votes if v[0] == period]
    if len(matching) < MIN_VOTES:
        return _histogram_fallback(rgb)

    def _sample_pair(vote: tuple) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
        _, _, axis, index, start, _ = vote
        if axis == "row":
            rgb_win = rgb[index, start : start + WINDOW_LEN, :]
        else:
            rgb_win = rgb[start : start + WINDOW_LEN, index, :]
        even_mask = (np.arange(len(rgb_win)) // period) % 2 == 0
        # Median, not mean: a handful of shadow-darkened cells within the
        # same window drag the mean toward the middle (measured: mean gave
        # (202,239) here vs the sheet's true (185,255)); the median is
        # robust to that tail and reproduces the prevailing colour instead.
        ga = tuple(int(v) for v in np.median(rgb_win[even_mask].astype(np.float64), axis=0))
        gb = tuple(int(v) for v in np.median(rgb_win[~even_mask].astype(np.float64), axis=0))
        d = colour_distance(ga, gb)
        sat_a, sat_b = max(ga) - min(ga), max(gb) - min(gb)
        if d <= MIN_GREY_DELTA or sat_a >= MAX_SATURATION or sat_b >= MAX_SATURATION:
            return None
        return ga, gb

    # Take the single best (highest-delta) vote per coarse spatial region
    # first, not a global top-N by delta: a sheet with one high-contrast
    # panel and one lower-contrast panel would otherwise have its top-N
    # monopolised entirely by the high-contrast panel's windows, and the
    # lower-contrast panel's real (but genuinely dimmer) checker colour
    # would never make it into `colour_pairs` at all -- confirmed on
    # Mockups/BATCH 01.jpg, where the props panel's checker so thoroughly
    # out-scored the terrain panel's on raw amplitude that the terrain
    # panel's own colour pair never surfaced without this.
    region_size = WINDOW_LEN * 2
    best_per_region: dict[tuple[int, int], tuple] = {}
    for vote in matching:
        _, _, axis, index, start, delta = vote
        if axis == "row":
            cx, cy = start + WINDOW_LEN / 2, index
        else:
            cx, cy = index, start + WINDOW_LEN / 2
        region = (int(cx // region_size), int(cy // region_size))
        if region not in best_per_region or delta > best_per_region[region][5]:
            best_per_region[region] = vote

    ranked = sorted(best_per_region.values(), key=lambda v: -v[5])
    colour_pairs = []
    for vote in ranked:
        pair = _sample_pair(vote)
        if pair is None:
            continue
        ga, gb = pair
        if not any(
            colour_distance(ga, existing_a) < 20 and colour_distance(gb, existing_b) < 20
            for existing_a, existing_b in colour_pairs
        ):
            colour_pairs.append((ga, gb))
        if len(colour_pairs) >= 8:
            break

    if not colour_pairs:
        return _histogram_fallback(rgb)

    _, confidence, *_ = max(matching, key=lambda v: v[5])
    grey_a, grey_b = colour_pairs[0]

    return CheckerReport(
        period=period,
        grey_a=grey_a,
        grey_b=grey_b,
        confidence=confidence,
        method="autocorrelation",
        ok=True,
        colour_pairs=colour_pairs,
    )


def _histogram_fallback(rgb: np.ndarray) -> CheckerReport:
    """Two most frequent low-saturation colours, used when autocorrelation
    can't find a confident period (e.g. a sheet with almost no bare
    background). Always flagged not-ok so the caller sends it to review."""
    flat = rgb.reshape(-1, 3)
    sat = flat.max(axis=1).astype(int) - flat.min(axis=1).astype(int)
    low_sat = flat[sat < MAX_SATURATION]
    if len(low_sat) == 0:
        return CheckerReport(
            period=MIN_PERIOD,
            grey_a=(255, 255, 255),
            grey_b=(200, 200, 200),
            confidence=0.0,
            method="histogram_fallback",
            ok=False,
            colour_pairs=[((255, 255, 255), (200, 200, 200))],
        )
    colours, counts = np.unique(low_sat, axis=0, return_counts=True)
    order = np.argsort(-counts)
    top = colours[order[: min(2, len(order))]]
    grey_a = tuple(int(v) for v in top[0])
    grey_b = tuple(int(v) for v in top[1]) if len(top) > 1 else grey_a
    return CheckerReport(
        period=16,
        grey_a=grey_a,
        grey_b=grey_b,
        confidence=0.0,
        method="histogram_fallback",
        ok=False,
        colour_pairs=[(grey_a, grey_b)],
    )


def classify_checkerboard(
    rgb: np.ndarray, report: CheckerReport, tolerance: float = 22.0
) -> np.ndarray:
    """Per-pixel boolean mask: True where the pixel matches either grey of
    ANY candidate checkerboard colour pair within `tolerance` (generous --
    JPEG ringing blends real edges into the background colour).

    Checking every pair in `report.colour_pairs`, not just the single
    best one, is what makes this work on sheets that lay out multiple
    panels with slightly different checker tones (see `CheckerReport`'s
    docstring) -- classifying against one global pair left an entire
    panel almost fully opaque on Mockups/BATCH 01.jpg."""
    flat = rgb.reshape(-1, 3).astype(np.float64)
    pairs = report.colour_pairs or [(report.grey_a, report.grey_b)]
    best = None
    for grey_a, grey_b in pairs:
        dist_a = np.linalg.norm(flat - np.array(grey_a), axis=1)
        dist_b = np.linalg.norm(flat - np.array(grey_b), axis=1)
        pair_min = np.minimum(dist_a, dist_b)
        best = pair_min if best is None else np.minimum(best, pair_min)
    is_checker = best <= tolerance
    return is_checker.reshape(rgb.shape[:2])


def majority_filter_3x3(mask: np.ndarray) -> np.ndarray:
    """One pass of 'the pixel becomes whatever >=5 of its 3x3 neighbours
    are', to kill isolated single-pixel misclassifications in either
    direction before erosion runs on the result."""
    h, w = mask.shape
    counts = np.zeros((h, w), dtype=np.int16)
    padded = np.pad(mask.astype(np.int16), 1, mode="edge")
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            counts += padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    return counts >= 5


def erode_3x3(mask: np.ndarray) -> np.ndarray:
    """Binary erosion: a pixel survives only if all 8 neighbours (+itself)
    are also True. Implemented as 9 shifted-copy ANDs -- no scipy needed."""
    h, w = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    result = np.ones((h, w), dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            result &= padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    return result


def repair_ring_colours(rgb: np.ndarray, opaque: np.ndarray, max_bfs: int = 3) -> tuple[
    np.ndarray, int, int
]:
    """JPEG blends sprite edges into the checkerboard; erode 1px then
    recolour the shaved ring from the nearest still-opaque ('eroded')
    pixel, discarding the blend. Returns (repaired_rgb, repaired_count,
    unresolved_count)."""
    eroded = erode_3x3(opaque)
    ring = opaque & ~eroded
    out = rgb.copy()
    h, w = opaque.shape
    repaired = 0
    unresolved = 0
    ring_coords = list(zip(*np.nonzero(ring), strict=False))
    for y, x in ring_coords:
        found = _bfs_nearest_eroded(eroded, y, x, h, w, max_bfs)
        if found is None:
            unresolved += 1
            continue
        fy, fx = found
        out[y, x] = rgb[fy, fx]
        repaired += 1
    return out, repaired, unresolved


def _bfs_nearest_eroded(
    eroded: np.ndarray, y0: int, x0: int, h: int, w: int, max_dist: int
) -> tuple[int, int] | None:
    visited = {(y0, x0)}
    queue: deque[tuple[int, int, int]] = deque([(y0, x0, 0)])
    while queue:
        y, x, dist = queue.popleft()
        if dist > 0 and eroded[y, x]:
            return y, x
        if dist >= max_dist:
            continue
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and (ny, nx) not in visited:
                visited.add((ny, nx))
                queue.append((ny, nx, dist + 1))
    return None


def fill_small_holes(is_checker: np.ndarray, max_hole_area: int = 64) -> np.ndarray:
    """Flip small interior checker-classified regions (not touching the
    sheet border) back to opaque -- almost certainly a misclassified grey
    art pixel, not real transparency. Real interior transparency is
    larger/border-connected; accepted false-negative tradeoff."""
    labels, n = label_components(is_checker)
    if n == 0:
        return is_checker
    h, w = is_checker.shape
    border_labels = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border_labels.discard(0)
    out = is_checker.copy()
    for label_id in range(1, n + 1):
        if label_id in border_labels:
            continue
        region = labels == label_id
        if region.sum() < max_hole_area:
            out[region] = False
    return out


def remove_small_opaque_specks(opaque: np.ndarray, max_speck_area: int = 20) -> np.ndarray:
    """Symmetric counterpart to `fill_small_holes`: flip small ISOLATED
    opaque blobs back to transparent. Soft-shadow-blended checker pixels
    that survive classification leave a sparse scatter of 1-3px opaque
    flecks in what should be clean background; because 8-connectivity
    treats even a single diagonal touch as "connected", enough scattered
    flecks turn dozens of genuinely separate sprites into one giant
    connected component before slicing ever gets a chance to tell them
    apart -- confirmed on Mockups/BATCH 01.jpg, where the raw alpha mask's
    largest connected component covered 709k of ~1.08M pixels before this
    cleanup. `max_speck_area` is deliberately small (default 20, versus
    fill_small_holes' 64) so it only eats true noise flecks, not a
    genuinely small accessory (a torch's flame, a gem) that a later merge
    step is supposed to reunite with its parent."""
    labels, n = label_components(opaque)
    if n == 0:
        return opaque
    out = opaque.copy()
    for label_id in range(1, n + 1):
        region = labels == label_id
        if region.sum() < max_speck_area:
            out[region] = False
    return out


def strip_frame_components(
    opaque: np.ndarray,
    bbox_area_frac: float = 0.15,
    max_fill_ratio: float = 0.6,
    max_strip_area: int = 60_000,
) -> tuple[np.ndarray, list[tuple[int, int, int, int]], list[tuple[int, int, int, int]]]:
    """Flip decorative border/frame/divider chrome back to transparent --
    but ONLY when the component being removed is small enough to
    plausibly BE just a thin line, never a guess at scale.

    A thin outline around a panel's edge (or a divider between panels) is
    a real connected component whose PIXELS are sparse but whose
    BOUNDING BOX spans a huge fraction of the sheet -- and
    `merge_boxes_by_gap`'s distance is a bbox-to-bbox distance, so a
    sheet-spanning bbox registers as "touching" every other component
    regardless of gap threshold, silently re-fusing everything the
    speck/hole cleanup just separated.

    `bbox_area_frac`/`max_fill_ratio` alone are NOT a safe trigger to
    delete a component, confirmed the hard way: on this project's own
    sheets, a component matching that exact "huge sparse bbox" pattern
    was sometimes a real ~58k px header bar (safe to remove) and
    sometimes 170k-250k px of REQUIRED real content -- the temple
    DAMAGED/SEALED/OVERGROWN renders on sheet 2, genuinely touching each
    other or the panel edge with no gap at all, which is not a "thin
    bridge" a bigger erosion radius can separate (tested up to radius 6
    with no change) but real 2D mass. Blanket-deleting by shape alone
    silently destroyed required art. `max_strip_area` is the fix: only
    ever auto-remove a component whose actual pixel AREA (not bbox) is
    small enough to plausibly be a header/border/divider line and
    nothing else (measured true chrome on this project's sheets tops out
    around 58k px) -- anything bigger that matches the bbox/fill-ratio
    shape is left untouched and reported as `ambiguous_boxes` instead of
    silently deleted, for a human to inspect via the review crop."""
    labels, n = label_components(opaque)
    if n == 0:
        return opaque, [], []
    h, w = opaque.shape
    sheet_area = h * w
    out = opaque.copy()
    stripped_boxes = []
    ambiguous_boxes = []
    for label_id in range(1, n + 1):
        region = labels == label_id
        area = int(region.sum())
        x0, y0, x1, y1 = bbox_of(region)
        bbox_area = (x1 - x0 + 1) * (y1 - y0 + 1)
        fill_ratio = area / bbox_area if bbox_area else 0.0
        if bbox_area >= bbox_area_frac * sheet_area and fill_ratio <= max_fill_ratio:
            if area <= max_strip_area:
                out[region] = False
                stripped_boxes.append((x0, y0, x1 + 1, y1 + 1))
            else:
                ambiguous_boxes.append((x0, y0, x1 + 1, y1 + 1))
    return out, stripped_boxes, ambiguous_boxes


def local_std_windows(gray: np.ndarray, window: int, stride: int) -> np.ndarray:
    """Sliding-window local standard deviation, used to tell a solid
    reference/comparison panel (near-zero local std) apart from a
    checkerboard (std ~ half the two greys' delta) -- a variance question,
    not a colour question, so it works regardless of the panel's actual
    shade."""
    h, w = gray.shape
    out_h = max(1, (h - window) // stride + 1)
    out_w = max(1, (w - window) // stride + 1)
    out = np.zeros((out_h, out_w))
    for j in range(out_h):
        for i in range(out_w):
            y0, x0 = j * stride, i * stride
            block = gray[y0 : y0 + window, x0 : x0 + window]
            out[j, i] = float(block.std()) if block.size else 0.0
    return out


# --------------------------------------------------------------------------
# A2 - connected components + merge
# --------------------------------------------------------------------------


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected components via iterative BFS/stack (no scipy). Fast
    enough at sheet resolution (~1M px, sub-second)."""
    h, w = mask.shape
    labels = np.zeros((h, w), dtype=np.int32)
    current = 0
    for y, x in np.argwhere(mask):
        y, x = int(y), int(x)
        if labels[y, x]:
            continue
        current += 1
        stack = [(y, x)]
        labels[y, x] = current
        while stack:
            cy, cx = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = current
                        stack.append((ny, nx))
    return labels, current


Box = tuple[int, int, int, int]  # x0, y0, x1, y1


def _box_gap(a: Box, b: Box) -> float:
    dx = max(0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0, max(a[1] - b[3], b[1] - a[3]))
    return math.hypot(dx, dy)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[ri] = rj

    def groups(self) -> list[list[int]]:
        buckets: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            buckets.setdefault(self.find(i), []).append(i)
        return list(buckets.values())


def merge_boxes_by_gap(boxes: list[Box], gap: float) -> list[list[int]]:
    """Union-find merge of boxes whose gap distance is < `gap`.

    Distances are always measured between the *original* boxes, never a
    group's enclosing rectangle: an enclosing box can span empty space (a
    tree in one corner merged with a rock in another), and any unrelated
    third box that merely falls inside that empty span would register a
    false near-zero gap to it, causing runaway merging across a whole
    sheet -- confirmed as a real bug (an entire sheet collapsing into one
    "sprite") before switching to this approach. Union-find's own
    transitivity already handles the "A-B close, B-C close" chaining
    case for free from a single pass over original-box pairs -- no
    repeated-pass box-growing is needed.
    """
    uf = _UnionFind(len(boxes))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _box_gap(boxes[i], boxes[j]) < gap:
                uf.union(i, j)
    return uf.groups()


# --------------------------------------------------------------------------
# A3 - scale
# --------------------------------------------------------------------------


def footprint_width(alpha: np.ndarray, bottom_frac: float = 0.33) -> int:
    """Widest point of a building's base slab, ignoring roof overhang: the
    90th-percentile opaque-row width within the bottom `bottom_frac` of the
    sprite's opaque bounding box (90th, not max, to be immune to a single
    stray shadow-pixel row)."""
    ys, _ = np.nonzero(alpha)
    y0, y1 = int(ys.min()), int(ys.max())
    band_height = max(1, round((y1 - y0 + 1) * bottom_frac))
    band_top = y1 - band_height + 1
    widths = []
    for row in range(band_top, y1 + 1):
        xs = np.nonzero(alpha[row])[0]
        if len(xs):
            widths.append(int(xs.max()) - int(xs.min()) + 1)
    if not widths:
        raise ValueError("footprint_width: empty bottom band")
    widths.sort()
    idx = int(round(0.9 * (len(widths) - 1)))
    return widths[idx]


def scale_for(kind: str, measured_width: int) -> float:
    footprint_class = KIND_FOOTPRINT[kind]
    return CLASS_WIDTH[footprint_class] / measured_width


# --------------------------------------------------------------------------
# A4 - anchors
# --------------------------------------------------------------------------


def anchor_building(alpha: np.ndarray, band_frac: float = 0.05) -> tuple[float, float]:
    """Anchor at the centroid of the lowest `band_frac` of opaque rows --
    the bottom-centre of the ground-footprint diamond, not the bbox
    centre, which roof overhang would skew."""
    ys, _ = np.nonzero(alpha)
    y0, y1 = int(ys.min()), int(ys.max())
    band_height = max(1, round((y1 - y0 + 1) * band_frac))
    band_top = y1 - band_height + 1
    band_xs = np.nonzero(alpha[band_top : y1 + 1])[1]
    return float(band_xs.mean()), float(y1)


def anchor_character(alpha: np.ndarray) -> tuple[float, float]:
    return anchor_building(alpha, band_frac=0.08)


def anchor_prop(alpha: np.ndarray) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox_of(alpha)
    return (x0 + x1) / 2.0, float(y1)


# --------------------------------------------------------------------------
# A5 - palette
# --------------------------------------------------------------------------


def bucket_palette_into_families(
    palette_rgb: list[tuple[int, int, int]], family_size: int = 4
) -> dict[str, dict[str, str]]:
    """Sort 64 clustered RGBs by hue, split into contiguous groups of 4,
    sort each group by lightness -> dark/mid/light/highlight. Preserves
    palette.ts's exact 4-shades-per-family contract while widening the
    family count (8 -> 16 for a 64-colour palette)."""
    if len(palette_rgb) % family_size != 0:
        raise ValueError("palette size must be a multiple of family_size")
    hsl = []
    for rgb in palette_rgb:
        hue, lightness, sat = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
        hsl.append((hue, lightness, sat, rgb))
    hsl.sort(key=lambda t: t[0])
    n_families = len(palette_rgb) // family_size
    shade_names = ("dark", "mid", "light", "highlight")
    out: dict[str, dict[str, str]] = {}
    for i in range(n_families):
        group = sorted(hsl[i * family_size : (i + 1) * family_size], key=lambda t: t[1])
        out[f"hue{i:02d}"] = {
            shade_names[j]: rgb_to_hex(group[j][3]) for j in range(family_size)
        }
    return out


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def palette_rgb_list(palette_json: dict[str, dict[str, str]]) -> list[tuple[int, int, int]]:
    out = []
    for values in palette_json.values():
        for hex_str in values.values():
            hex_str = hex_str.lstrip("#")
            out.append(tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4)))
    return out


def snap_to_palette(
    rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]
) -> tuple[int, int, int]:
    """Nearest-RGB-distance snap. Python twin of palette.ts's
    snapToPalette -- deliberately reimplemented, not cross-language
    imported, since the two run in different processes/languages."""
    best = palette[0]
    best_dist = colour_distance(rgb, best)
    for candidate in palette[1:]:
        dist = colour_distance(rgb, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate
    return best


# --------------------------------------------------------------------------
# overrides.json - the one human-edit file
# --------------------------------------------------------------------------


@dataclass
class OverrideEntry:
    name: str | None = None
    anchor: dict[str, float] | None = None
    anchor_source: str | None = None
    notes: str = ""
    stale: bool = False
    fps: int | None = field(default=None)


def read_overrides(path: Path = OVERRIDES_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_overrides_merge(
    new_ids: list[str], path: Path = OVERRIDES_PATH
) -> dict[str, dict[str, Any]]:
    """Read-modify-write: never drops an existing key or clobbers a
    human-entered `name`; new ids from a rerun are appended with
    `name: None`, ids that vanished keep their entry with `stale: True`."""
    existing = read_overrides(path)
    for sprite_id in new_ids:
        if sprite_id not in existing:
            existing[sprite_id] = {"name": None, "anchor": None, "notes": ""}
    for sprite_id, entry in existing.items():
        if sprite_id not in new_ids:
            entry["stale"] = True
    json_dump(existing, path)
    return existing


def merge_anchor_into_overrides(
    anchors: dict[str, tuple[float, float]], path: Path = OVERRIDES_PATH
) -> dict[str, dict[str, Any]]:
    """Fill `anchor` only where currently None -- a hand-entered anchor
    always wins and a rerun never overwrites it."""
    existing = read_overrides(path)
    for sprite_id, (x, y) in anchors.items():
        entry = existing.setdefault(sprite_id, {"name": None, "anchor": None, "notes": ""})
        if entry.get("anchor") is None:
            entry["anchor"] = {"x": x, "y": y}
            entry["anchor_source"] = "computed"
    json_dump(existing, path)
    return existing
