"""A4 - compute anchors for every scaled sprite.

Anchor coordinates are sprite-local pixel offsets (origin = frame
top-left) -- the one contract this pipeline and the renderer must agree
on, and the one thing that can't be checked from this side. Buildings
anchor at the centroid of the lowest 5% of opaque rows (the ground
footprint's bottom-centre, not the bbox centre, which roof overhang would
skew); characters at feet-centre (a smaller band, feet are a smaller
fraction of a tall figure); props at exact bbox-bottom-centre.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from tools.art.common import (
    ART,
    KIND_FOOTPRINT,
    alpha_mask,
    anchor_building,
    anchor_character,
    anchor_prop,
    load_rgba,
    merge_anchor_into_overrides,
    read_overrides,
)

SCALED_DIR = ART / "scaled"
ANCHORED_DIR = ART / "anchored"

TEST_TILE_SIZE = (128, 64)
TEST_TILE_SMALL = (64, 32)


def _category_of(name: str) -> str:
    if name.startswith(("terrain_", "prop_", "fx_")):
        return name.split("_", 1)[0]
    if name.startswith("monument_tier_"):
        return "building"
    parts = name.split("_")
    if parts[0] in KIND_FOOTPRINT:
        return "building"
    return "agent"


def _draw_test_tile(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.polygon(
        [(w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)],
        outline=(255, 0, 255, 255),
        width=2,
    )
    return img


def _composite_check(
    sprite: Image.Image, anchor: tuple[float, float], tile_size: tuple[int, int]
) -> Image.Image:
    tile = _draw_test_tile(tile_size)
    canvas_size = (
        max(tile_size[0], sprite.width) + 20,
        tile_size[1] + sprite.height + 20,
    )
    canvas = Image.new("RGBA", canvas_size, (40, 40, 40, 255))
    tile_x = canvas.width // 2 - tile_size[0] // 2
    tile_y = canvas.height - tile_size[1] - 10
    canvas.alpha_composite(tile, (tile_x, tile_y))
    anchor_x, anchor_y = anchor
    sprite_x = tile_x + tile_size[0] // 2 - round(anchor_x)
    sprite_y = tile_y + tile_size[1] // 2 - round(anchor_y)
    canvas.alpha_composite(sprite, (sprite_x, sprite_y))
    return canvas


def main() -> int:
    overrides = read_overrides()
    named = {sid: e for sid, e in overrides.items() if e.get("name") and e["name"] != "-"}

    anchors: dict[str, tuple[float, float]] = {}
    check_images: list[tuple[str, Image.Image]] = []

    for sprite_id, entry in named.items():
        name = entry["name"]
        base_name = name.split("@")[0]
        filename = name.replace("@", "_f")
        src = SCALED_DIR / f"{filename}.png"
        if not src.exists():
            continue
        rgba = load_rgba(src)
        alpha = alpha_mask(rgba)
        if not alpha.any():
            continue
        category = _category_of(base_name)

        if category == "building":
            x, y = anchor_building(alpha)
            tile_size = TEST_TILE_SIZE
        elif category == "agent":
            x, y = anchor_character(alpha)
            tile_size = TEST_TILE_SMALL
        else:
            x, y = anchor_prop(alpha)
            tile_size = TEST_TILE_SMALL

        anchors[sprite_id] = (x, y)

        if category in ("building", "agent"):
            sprite_img = Image.fromarray(rgba, "RGBA")
            check = _composite_check(sprite_img, (x, y), tile_size)
            check_images.append((name, check))

    merge_anchor_into_overrides(anchors)

    ANCHORED_DIR.mkdir(parents=True, exist_ok=True)
    figures = []
    for name, img in check_images:
        out_path = ANCHORED_DIR / f"{name}_check.png"
        img.convert("RGB").save(out_path)
        figures.append(
            f'<figure><img src="{out_path.name}"><figcaption>{name}</figcaption></figure>'
        )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Anchor verification</title>
<style>
body {{ background: #222; color: #eee; font-family: sans-serif; margin: 0; padding: 16px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, 180px); gap: 8px; }}
figure {{ margin: 0; padding: 8px; background: #333; border: 1px solid #555; text-align: center; }}
img {{ max-width: 160px; max-height: 160px; display: block; margin: 0 auto; }}
figcaption {{ font-size: 10px; margin-top: 4px; word-break: break-all; }}
</style></head>
<body>
<h1>Anchor verification ({len(figures)})</h1>
<p>Anchor should land on the magenta diamond's centre. Misalignment reads
as "floating off the tile".</p>
<div class="grid">
{"".join(figures)}
</div>
</body></html>
"""
    (ANCHORED_DIR / "contact_sheet.html").write_text(html, encoding="utf-8")

    print(f"Computed {len(anchors)} anchors.")
    print(f"Review: {ANCHORED_DIR / 'contact_sheet.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
