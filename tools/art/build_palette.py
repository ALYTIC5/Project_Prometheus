"""A5 - derive a 64-colour sprite-quantization palette from every scaled sprite.

Collects every opaque pixel across art/scaled/*.png plus every raw PixelLab
character frame (art/characters/*/*/rotations/*.png -- pooled so drawn
renderer elements cohere with the character art, per pack_atlas.py's
CHARACTER_ROTATION_RE branch, but the characters themselves are never
quantized against the result), runs Pillow's
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

import colorsys
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
CHARACTERS_DIR = ART / "characters"
PALETTE_COLOURS = 64
MAX_SAMPLES = 2_000_000
RANDOM_SEED = 0xA27

# Measured against the approved art direction: the recovered-JPEG source art
# clusters entirely under L~0.29 (nothing above #4A4A45), while the target
# has real highlights near L~0.75-0.85. A histogram stretch on HLS lightness
# -- remap the CLUSTERED PALETTE's actual [min, max] lightness linearly onto
# [LIFT_FLOOR, LIFT_CEILING] -- is calibrated to the real measured gap rather
# than an arbitrary curve, is a pure function of the input (deterministic,
# per CLAUDE.md), and is fully reversible (these 4 numbers are the entire
# transform, recorded in palette_report.json). Saturation gets a modest
# uniform boost for the same reason (measured median 0.17 vs target 0.25).
LIFT_FLOOR = 0.18
LIFT_CEILING = 0.88
SATURATION_BOOST = 1.15


def _modal_colour(pixels: np.ndarray) -> np.ndarray:
    colours, counts = np.unique(pixels, axis=0, return_counts=True)
    return colours[int(np.argmax(counts))]


def lift_lightness_and_saturation(
    palette_rgb: list[tuple[int, int, int]],
    floor: float = LIFT_FLOOR,
    ceiling: float = LIFT_CEILING,
    saturation_boost: float = SATURATION_BOOST,
) -> tuple[list[tuple[int, int, int]], dict]:
    """Linearly remap the palette's actual lightness range onto [floor, ceiling],
    preserving hue, and boost saturation uniformly (capped at 1.0). Returns the
    lifted palette plus the before/after range for the report."""
    hls = [colorsys.rgb_to_hls(r / 255, g / 255, b / 255) for r, g, b in palette_rgb]
    lightness_values = [lightness for _, lightness, _ in hls]
    l_min, l_max = min(lightness_values), max(lightness_values)
    span = l_max - l_min

    lifted: list[tuple[int, int, int]] = []
    for hue, lightness, saturation in hls:
        if span > 1e-9:
            new_lightness = floor + (lightness - l_min) / span * (ceiling - floor)
        else:
            new_lightness = (floor + ceiling) / 2
        new_saturation = min(1.0, saturation * saturation_boost)
        nr, ng, nb = colorsys.hls_to_rgb(hue, new_lightness, new_saturation)
        lifted.append((round(nr * 255), round(ng * 255), round(nb * 255)))

    report = {
        "floor": floor,
        "ceiling": ceiling,
        "saturation_boost": saturation_boost,
        "lightness_before": {"min": round(l_min, 4), "max": round(l_max, 4)},
    }
    return lifted, report


def main() -> int:
    from PIL import Image

    files = sorted(SCALED_DIR.glob("*.png"))
    if not files:
        print(f"No scaled sprites in {SCALED_DIR} -- run normalize_scale first", file=sys.stderr)
        return 1
    # PixelLab character art is pooled into the same union palette (so
    # programmatic renderer elements drawn from it cohere with the art) but
    # the characters themselves are never re-quantized to it -- see
    # pack_atlas.py's CHARACTER_ROTATION_RE branch.
    files = files + sorted(CHARACTERS_DIR.glob("*/*/rotations/*.png"))

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

    lifted_rgb, lift_report = lift_lightness_and_saturation(palette_rgb)
    families = bucket_palette_into_families(lifted_rgb, family_size=4)
    json_dump(families, SPRITES_DIR / "sprite_palette.json")

    # population_share is measured against the ORIGINAL clustered colour --
    # that's what pixels were actually quantized to -- not the lifted one.
    quant_arr = np.array(quantized.convert("RGB"))
    flat_quant = quant_arr.reshape(-1, 3)[: len(population)]
    report_entries = []
    for i, (rgb, lifted) in enumerate(zip(palette_rgb, lifted_rgb, strict=False)):
        share = float((flat_quant == np.array(rgb)).all(axis=1).mean())
        report_entries.append(
            {
                "index": i,
                "hex": rgb_to_hex(rgb),
                "rgb": list(rgb),
                "lifted_hex": rgb_to_hex(lifted),
                "lifted_rgb": list(lifted),
                "population_share": round(share, 5),
            }
        )

    json_dump(
        {
            "sampled_pixels": int(len(population)),
            "sources": len(files),
            "lift": lift_report,
            "entries": report_entries,
        },
        ART / "palette_report.json",
    )

    low_share = [e for e in report_entries if e["population_share"] < 0.0005]
    print(f"Wrote {SPRITES_DIR / 'sprite_palette.json'} (16 families x 4 shades = 64 colours)")
    print(f"Sampled {len(population):,} pixels from {len(files)} sprites")
    print(
        f"Lightness lift: {lift_report['lightness_before']['min']:.3f}-"
        f"{lift_report['lightness_before']['max']:.3f} -> {LIFT_FLOOR}-{LIFT_CEILING}"
    )
    if low_share:
        print(f"{len(low_share)} palette entries have near-zero population share (see report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
