"""R1 (Greek Rebuild) - Theme Lock law T3 enforcement.

Validates a downloaded PixelLab asset (a single PNG) against what was
requested: canvas size, non-empty alpha, and edge-clipping (a sprite whose
opaque content touches the canvas border by more than `edge_tolerance` px is
flagged -- PixelLab's own canvas-size drift, documented repeatedly in
art/RESUME.md across prior sessions, means a request for one size can come
back a different size silently; this is the check that catches it instead of
trusting the request).

Direction-count and view are NOT independently verifiable from a single PNG
(PixelLab's own response already states them; this checks the artifact those
claims produced, not the claims themselves) -- callers should cross-check the
tool response's own `directions`/`view` fields against what was requested,
this module only covers what pixel inspection can actually catch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class AssetCheckResult:
    ok: bool
    actual_size: tuple[int, int]
    requested_size: int | tuple[int, int] | None
    size_matches: bool
    has_alpha: bool
    is_empty: bool
    clipped_edges: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def check_asset(
    path: Path,
    requested_size: int | tuple[int, int] | None = None,
    edge_tolerance: int = 1,
    allow_edge_contact: bool = False,
) -> AssetCheckResult:
    """`allow_edge_contact`: set for tiles -- a ground tile is supposed to fill
    its canvas edge to edge, so edge contact there is correct, not clipping.
    `requested_size` is a square side length, or a (width, height) pair for
    non-square canvases (e.g. upright props needing extra height)."""
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    width, height = img.size
    alpha = arr[:, :, 3]
    has_alpha = bool((alpha < 255).any() or (alpha == 0).any())
    is_empty = bool((alpha == 0).all())

    errors: list[str] = []

    size_matches = True
    if requested_size is not None:
        want_w, want_h = (
            requested_size if isinstance(requested_size, tuple) else (requested_size,) * 2
        )
        size_matches = width == want_w and height == want_h
        if not size_matches:
            errors.append(f"size mismatch: requested {want_w}x{want_h}, got {width}x{height}")

    if is_empty:
        errors.append("image is fully transparent (empty)")

    clipped_edges: list[str] = []
    if not is_empty and not allow_edge_contact:
        opaque = alpha > 0
        ys, xs = np.nonzero(opaque)
        if ys.min() <= edge_tolerance:
            clipped_edges.append("top")
        if ys.max() >= height - 1 - edge_tolerance:
            clipped_edges.append("bottom")
        if xs.min() <= edge_tolerance:
            clipped_edges.append("left")
        if xs.max() >= width - 1 - edge_tolerance:
            clipped_edges.append("right")
        if clipped_edges:
            errors.append(f"content clips the canvas edge: {', '.join(clipped_edges)}")

    return AssetCheckResult(
        ok=not errors,
        actual_size=(width, height),
        requested_size=requested_size,
        size_matches=size_matches,
        has_alpha=has_alpha,
        is_empty=is_empty,
        clipped_edges=clipped_edges,
        errors=errors,
    )


if __name__ == "__main__":
    import sys

    from tools.art import compose_prompt
    from tools.art.scale import check_scale

    argv = sys.argv[1:]
    if "--key" not in argv or argv.index("--key") + 1 >= len(argv):
        print(
            "usage: python -m tools.art.check_asset <path.png> [requested_size] --key <theme key>\n"
            "--key is mandatory: every asset is scale-checked (law W11).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    key = argv[argv.index("--key") + 1]
    args = [a for i, a in enumerate(argv) if a != "--key" and (i == 0 or argv[i - 1] != "--key")]
    requested: int | tuple[int, int] | None = None
    if len(args) > 1:
        requested = tuple(int(x) for x in args[1].split("x")) if "x" in args[1] else int(args[1])  # type: ignore[assignment]
    is_tile = compose_prompt._find_entry(key)[0] == "tiles"
    result = check_asset(Path(args[0]), requested_size=requested, allow_edge_contact=is_tile)
    scale = check_scale(Path(args[0]), key)
    errors = result.errors + [f"scale: {e}" for e in scale.errors]
    if not errors:
        print(
            f"OK: {result.actual_size[0]}x{result.actual_size[1]}, "
            f"content {scale.content_size}, scale {scale.expected}"
        )
    else:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
