"""A5 - derive a 64-colour sprite-quantization palette from every scaled sprite.

Collects every opaque pixel across art/scaled/*.png, runs Pillow's
built-in median-cut quantizer once on the pooled population (not
per-sheet, which would let each sheet's palette drift from the others),
and writes frontend/src/sprites/sprite_palette.json in the same
structural shape palette.ts's renderer palette uses:
{family: {dark,mid,light,highlight}} -- 16 families x 4 shades = 64
colours. This is a SEPARATE file from palette.json: palette.json is the
renderer's hand-authored 8-family semantic palette (PALETTE['blue.dark']
etc, read by frontend/src/render/*.ts) and must never be overwritten by
this pipeline -- the two serve different consumers (procedural Pixi
fills vs. recovered-art colour quantization) and happened to collide
under one filename once before, breaking every renderer colour lookup.
"""

from __future__ import annotations

import sys

import numpy as np

from tools.art.common import (
    ART,
    SPRITES_DIR,
    alpha_mask,
    bucket_palette_into_families,
    json_dump,
    load_rgba,
    rgb_to_hex,
)

SCALED_DIR = ART / "scaled"
PALETTE_COLOURS = 64
MAX_SAMPLES = 2_000_000
RANDOM_SEED = 0xA27


def _modal_colour(pixels: np.ndarray) -> np.ndarray:
    colours, counts = np.unique(pixels, axis=0, return_counts=True)
    return colours[int(np.argmax(counts))]


def main() -> int:
    from PIL import Image

    files = sorted(SCALED_DIR.glob("*.png"))
    if not files:
        print(f"No scaled sprites in {SCALED_DIR} -- run normalize_scale first", file=sys.stderr)
        return 1

    samples = []
    for f in files:
        rgba = load_rgba(f)
        mask = alpha_mask(rgba)
        if mask.any():
            samples.append(rgba[mask][:, :3])
    population = np.concatenate(samples, axis=0)

    rng = np.random.default_rng(RANDOM_SEED)
    if len(population) > MAX_SAMPLES:
        idx = rng.choice(len(population), MAX_SAMPLES, replace=False)
        population = population[idx]

    side = int(np.ceil(np.sqrt(len(population))))
    strip = np.zeros((side * side, 3), dtype=np.uint8)
    strip[: len(population)] = population
    if side * side > len(population):
        strip[len(population) :] = _modal_colour(population)
    synth = Image.fromarray(strip.reshape(side, side, 3), "RGB")

    quantized = synth.quantize(
        colors=PALETTE_COLOURS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )
    flat_palette = quantized.getpalette()[: PALETTE_COLOURS * 3]
    palette_rgb = [
        (flat_palette[i * 3], flat_palette[i * 3 + 1], flat_palette[i * 3 + 2])
        for i in range(PALETTE_COLOURS)
    ]

    families = bucket_palette_into_families(palette_rgb, family_size=4)
    json_dump(families, SPRITES_DIR / "sprite_palette.json")

    # population_share per palette entry, for the report only.
    quant_arr = np.array(quantized.convert("RGB"))
    flat_quant = quant_arr.reshape(-1, 3)[: len(population)]
    report_entries = []
    for i, rgb in enumerate(palette_rgb):
        share = float((flat_quant == np.array(rgb)).all(axis=1).mean())
        report_entries.append(
            {
                "index": i,
                "hex": rgb_to_hex(rgb),
                "rgb": list(rgb),
                "population_share": round(share, 5),
            }
        )

    json_dump(
        {
            "sampled_pixels": int(len(population)),
            "sources": len(files),
            "entries": report_entries,
        },
        ART / "palette_report.json",
    )

    low_share = [e for e in report_entries if e["population_share"] < 0.0005]
    print(f"Wrote {SPRITES_DIR / 'sprite_palette.json'} (16 families x 4 shades = 64 colours)")
    print(f"Sampled {len(population):,} pixels from {len(files)} sprites")
    if low_share:
        print(f"{len(low_share)} palette entries have near-zero population share (see report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
