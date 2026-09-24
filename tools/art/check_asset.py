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
    requested_size: int | None
    size_matches: bool
    has_alpha: bool
    is_empty: bool
    clipped_edges: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def check_asset(
    path: Path,
    requested_size: int | None = None,
    edge_tolerance: int = 1,
) -> AssetCheckResult:
    img = Image.open(path).convert("RGBA")
    arr = np.array(img)
    width, height = img.size
    alpha = arr[:, :, 3]
    has_alpha = bool((alpha < 255).any() or (alpha == 0).any())
    is_empty = bool((alpha == 0).all())

    errors: list[str] = []

    size_matches = True
    if requested_size is not None:
        size_matches = width == requested_size and height == requested_size
        if not size_matches:
            errors.append(
                f"size mismatch: requested {requested_size}x{requested_size}, "
                f"got {width}x{height}"
            )

    if is_empty:
        errors.append("image is fully transparent (empty)")

    clipped_edges: list[str] = []
    if not is_empty:
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

    if len(sys.argv) < 2:
        print("usage: python -m tools.art.check_asset <path.png> [requested_size]", file=sys.stderr)
        raise SystemExit(1)
    requested = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result = check_asset(Path(sys.argv[1]), requested_size=requested)
    if result.ok:
        print(f"OK: {result.actual_size[0]}x{result.actual_size[1]}")
    else:
        for error in result.errors:
            print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
