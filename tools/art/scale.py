"""World-scale enforcement (Theme Lock law W11).

Two gates, both fail CLOSED:

- `preflight(key, canvas)` runs BEFORE any PixelLab job is queued. It refuses
  a canvas that cannot hold the asset at world scale, and refuses any asset
  whose category has no scale rule yet -- no generation is spent on an asset
  whose correct size nobody has decided.
- `check_scale(path, key)` runs on every downloaded asset (called by
  check_asset when a key is given) and measures the opaque content's
  bounding box against the same rules.

Buildings are sized from the BACKEND footprint
(prometheus/world/construction.py BUILDING_LOCATIONS), which is what the
renderer actually draws (building.ts: halfW = width * TILE_WIDTH / 2) -- not
from art/theme.yaml's `footprint` field. All numbers live in art/theme.yaml
under `scale:`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from prometheus.world.construction import BUILDING_LOCATIONS
from tools.art import compose_prompt


@dataclass
class ScaleResult:
    ok: bool
    key: str
    category: str
    errors: list[str] = field(default_factory=list)
    content_size: tuple[int, int] | None = None
    expected: str = ""


def _rules() -> dict[str, Any]:
    theme = compose_prompt._load_theme()
    if "scale" not in theme:
        raise KeyError("art/theme.yaml has no `scale:` section")
    rules: dict[str, Any] = theme["scale"]
    return rules


def _category(key: str) -> str:
    category, _ = compose_prompt._find_entry(key)
    return category


def _building_width(key: str, tile_px: int) -> int:
    loc = BUILDING_LOCATIONS.get(key)
    if loc is None:
        raise KeyError(
            f"building {key!r} has no backend footprint in "
            "prometheus/world/construction.py BUILDING_LOCATIONS -- add it there first"
        )
    return int((loc["width"] + loc["height"]) * tile_px / 2)


def _content_bbox(path: Path) -> tuple[int, int] | None:
    alpha = np.array(Image.open(path).convert("RGBA"))[:, :, 3] > 0
    if not alpha.any():
        return None
    ys, xs = np.nonzero(alpha)
    return int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def _category_rule(category: str, key: str) -> tuple[dict[str, Any] | None, str | None]:
    rules = _rules()
    rule = rules.get("categories", {}).get(category)
    if rule is None:
        return None, (
            f"no scale rule for category {category!r} ({key}) -- decide its world "
            "size in art/theme.yaml `scale.categories` before generating it"
        )
    return rule, None


def _prop_max_width(key: str, rule: dict[str, Any]) -> int:
    overrides: dict[str, int] = rule.get("max_width_px_overrides", {})
    return int(overrides.get(key, rule["max_width_px"]))


def _prop_canvas_height(key: str, rule: dict[str, Any]) -> int:
    overrides: dict[str, int] = rule.get("canvas_height_overrides", {})
    return int(overrides.get(key, rule.get("canvas_height", rule["canvas"])))


def prop_canvas(key: str) -> tuple[int, int]:
    """(width, height) to request for a `props` key. Upright props (trees,
    bushes) get a taller canvas via `canvas_height_overrides` -- a square
    canvas crops their crown (R2 pilot: olive_tree clipped top+bottom at
    32x32). Width stays fixed at `scale.categories.props.canvas`."""
    category = _category(key)
    if category != "props":
        raise ValueError(f"{key!r} is category {category!r}, not props")
    rule, err = _category_rule(category, key)
    if rule is None:
        raise KeyError(err)
    return int(rule["canvas"]), _prop_canvas_height(key, rule)


def _normalize(canvas: int | tuple[int, int]) -> tuple[int, int]:
    return canvas if isinstance(canvas, tuple) else (canvas, canvas)


def preflight(key: str, canvas: int | tuple[int, int]) -> ScaleResult:
    """Call before queueing a PixelLab job for `key`. `canvas` is a square
    side length, or a (width, height) pair -- required for props via
    `prop_canvas(key)`, since upright props need canvas_height > canvas."""
    width, height = _normalize(canvas)
    category = _category(key)
    rule, err = _category_rule(category, key)
    if rule is None:
        return ScaleResult(False, key, category, [err or ""])
    tile_px = int(_rules()["tile_px"])
    errors: list[str] = []
    expected = ""
    kind = rule["rule"]
    if kind == "footprint":
        try:
            target = _building_width(key, tile_px)
        except KeyError as exc:
            return ScaleResult(False, key, category, [str(exc)])
        margin = int(rule.get("canvas_margin_px", 0))
        expected = f"content width ~{target}px (backend footprint)"
        if width < target + margin:
            errors.append(
                f"canvas {width}px cannot hold a {target}px-wide building "
                f"(+{margin}px margin); need >= {target + margin}"
            )
    elif kind == "tile":
        expected = f"tile width {tile_px}px"
        if width != tile_px:
            errors.append(f"tile canvas must be {tile_px}px, got {width}")
    elif kind == "max_width":
        want_w = int(rule["canvas"])
        want_h = _prop_canvas_height(key, rule)
        expected = f"canvas {want_w}x{want_h}, content <= {_prop_max_width(key, rule)}px wide"
        if (width, height) != (want_w, want_h):
            errors.append(f"{key} canvas must be {want_w}x{want_h}, got {width}x{height}")
    elif kind == "character":
        want = int(rule["canvas"])
        expected = (
            f"canvas {want}x{want}, content {rule['min_height_px']}-{rule['max_height_px']}px tall"
        )
        if (width, height) != (want, want):
            errors.append(f"{category} canvas must be {want}x{want}, got {width}x{height}")
    else:
        errors.append(f"unknown scale rule {kind!r} for category {category!r}")
    return ScaleResult(not errors, key, category, errors, expected=expected)


def check_scale(path: Path, key: str) -> ScaleResult:
    """Measure a downloaded asset's opaque content against its world-scale rule."""
    category = _category(key)
    rule, err = _category_rule(category, key)
    if rule is None:
        return ScaleResult(False, key, category, [err or ""])
    tile_px = int(_rules()["tile_px"])
    bbox = _content_bbox(path)
    if bbox is None:
        return ScaleResult(False, key, category, ["image is empty"])
    width = bbox[0]
    errors: list[str] = []
    expected = ""
    kind = rule["rule"]
    if kind == "footprint":
        try:
            target = _building_width(key, tile_px)
        except KeyError as exc:
            return ScaleResult(False, key, category, [str(exc)], bbox)
        lo = round(target * float(rule["min_ratio"]))
        hi = round(target * float(rule["max_ratio"]))
        expected = f"{lo}-{hi}px wide (backend footprint {target}px)"
        if not lo <= width <= hi:
            errors.append(f"content {width}px wide, expected {expected}")
    elif kind == "tile":
        expected = f"{tile_px}px wide"
        if width != tile_px:
            errors.append(f"tile content {width}px wide, expected {tile_px}")
    elif kind == "max_width":
        max_w = _prop_max_width(key, rule)
        expected = f"<= {max_w}px wide"
        if width > max_w:
            errors.append(f"content {width}px wide, max {max_w}px ({category} at world scale)")
    elif kind == "character":
        lo, hi = int(rule["min_height_px"]), int(rule["max_height_px"])
        content_h = bbox[1]
        expected = f"{lo}-{hi}px tall"
        if not lo <= content_h <= hi:
            errors.append(f"content {content_h}px tall, expected {expected} ({category})")
    else:
        errors.append(f"unknown scale rule {kind!r} for category {category!r}")
    return ScaleResult(not errors, key, category, errors, bbox, expected)
