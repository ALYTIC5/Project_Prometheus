"""World Track W0 -- render any set of art/raw/characters/ keys x
directions x animations into one PNG grid at 2x nearest-neighbour, so a
human (or Claude, via the Read tool) can actually look at the imported
art in one image instead of opening 300+ individual PNGs.

Reads directly from art/raw/characters/<key>/<state>/<anim>/<direction>/
<frame>.png (ingest_pixellab_export.py's output) plus art/registry.json
for the key list -- no dependency on the OLD art/scaled/ pipeline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from tools.art.common import ART

RAW_CHARACTERS_DIR = ART / "raw" / "characters"
REGISTRY_PATH = ART / "registry.json"
ROTATION_ORDER = [
    "south",
    "south-east",
    "east",
    "north-east",
    "north",
    "north-west",
    "west",
    "south-west",
]
SCALE = 2
LABEL_HEIGHT = 14
PADDING = 4


def _load_registry() -> dict[str, dict]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def render_contact_sheet(
    keys: list[str], *, state: str = "idle", anim: str = "rotation", frame: int = 0
) -> Image.Image:
    cells: list[tuple[str, Image.Image | None]] = []
    for key in keys:
        for direction in ROTATION_ORDER:
            path = RAW_CHARACTERS_DIR / key / state / anim / direction / f"{frame}.png"
            img = Image.open(path).convert("RGBA") if path.exists() else None
            cells.append((f"{key}\n{direction}", img))

    cell_w = max((img.width for _, img in cells if img is not None), default=48) * SCALE
    cell_h = max((img.height for _, img in cells if img is not None), default=48) * SCALE
    cols = len(ROTATION_ORDER)
    rows = len(keys)

    sheet_w = cols * (cell_w + PADDING) + PADDING
    sheet_h = rows * (cell_h + LABEL_HEIGHT + PADDING) + PADDING
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (30, 30, 30, 255))
    draw = ImageDraw.Draw(sheet)

    for i, (label, img) in enumerate(cells):
        row, col = divmod(i, cols)
        x = PADDING + col * (cell_w + PADDING)
        y = PADDING + row * (cell_h + LABEL_HEIGHT + PADDING)
        if img is not None:
            scaled = img.resize((img.width * SCALE, img.height * SCALE), Image.NEAREST)
            sheet.paste(scaled, (x, y), scaled)
        else:
            draw.rectangle([x, y, x + cell_w, y + cell_h], outline=(120, 40, 40, 255))
        if col == 0:
            draw.text((x, y + cell_h + 1), label.split("\n")[0], fill=(220, 220, 220, 255))

    return sheet.convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", nargs="*", default=None, help="Registry keys to render; default: all")
    parser.add_argument("--state", default="idle")
    parser.add_argument("--out", type=Path, default=Path("artifacts/art/contact_mockups.png"))
    parser.add_argument(
        "--only-existing",
        action="store_true",
        help="Skip keys whose account_status is not_found (nothing new to see for those).",
    )
    args = parser.parse_args()

    registry = _load_registry()
    all_keys = sorted(k for k in registry if not k.startswith("_"))
    keys = args.keys or all_keys
    if args.only_existing:
        keys = [k for k in keys if registry.get(k, {}).get("account_status") != "not_found"]

    sheet = render_contact_sheet(keys, state=args.state)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.out)
    print(f"Wrote {args.out} ({sheet.width}x{sheet.height}px, {len(keys)} characters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
