"""prometheus/main.py's Next.js static-export path resolution.

Regression for a real bug: a route-shaped path (e.g. "sprites") that also
has a same-named directory copied from public/ (e.g. public/sprites/*.png)
was resolving to that directory and silently falling through to the SPA
shell instead of the page's `<path>.html` export.
"""
from __future__ import annotations

from pathlib import Path

from prometheus.main import resolve_static_path


def test_resolves_root_page(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("root")
    assert resolve_static_path("", tmp_path) == tmp_path / "index.html"


def test_route_shadowed_by_same_named_public_directory_still_resolves(tmp_path: Path) -> None:
    # Mirrors the real /sprites collision: a page export `sprites.html`
    # alongside a `sprites/` directory copied from public/.
    (tmp_path / "sprites.html").write_text("page")
    sprites_dir = tmp_path / "sprites"
    sprites_dir.mkdir()
    (sprites_dir / "characters_atlas.png").write_bytes(b"\x89PNG")

    assert resolve_static_path("sprites", tmp_path) == tmp_path / "sprites.html"


def test_static_asset_under_a_route_shaped_directory_still_resolves(tmp_path: Path) -> None:
    sprites_dir = tmp_path / "sprites"
    sprites_dir.mkdir()
    (sprites_dir / "characters_atlas.png").write_bytes(b"\x89PNG")

    resolved = resolve_static_path("sprites/characters_atlas.png", tmp_path)
    assert resolved == sprites_dir / "characters_atlas.png"


def test_unresolvable_path_returns_none(tmp_path: Path) -> None:
    assert resolve_static_path("does/not/exist", tmp_path) is None
