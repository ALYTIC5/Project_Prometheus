"""tools/art/common.py's palette family/shade bucketing (A5) and
nearest-colour snap -- the direct guard on palette.ts's structural
contract (exactly 4 shades per family: dark/mid/light/highlight).
"""
from __future__ import annotations

import colorsys

from tools.art.common import bucket_palette_into_families, snap_to_palette


def _synthetic_64_colours() -> list[tuple[int, int, int]]:
    """64 RGBs spanning the hue circle, 4 lightness levels each, so the
    bucketing has real structure to sort instead of degenerating on
    near-identical greys."""
    colours = []
    for hue_step in range(16):
        for lightness_step in range(4):
            hue = hue_step / 16
            lightness = 0.2 + lightness_step * 0.2
            r, g, b = colorsys.hls_to_rgb(hue, lightness, 0.6)
            colours.append((int(r * 255), int(g * 255), int(b * 255)))
    return colours


def test_bucketing_produces_16_families_of_4() -> None:
    palette = bucket_palette_into_families(_synthetic_64_colours())
    assert len(palette) == 16
    for family in palette.values():
        assert set(family.keys()) == {"dark", "mid", "light", "highlight"}


def test_shades_are_lightness_ascending_within_family() -> None:
    palette = bucket_palette_into_families(_synthetic_64_colours())
    for family in palette.values():
        lightnesses = []
        for shade in ("dark", "mid", "light", "highlight"):
            hex_str = family[shade].lstrip("#")
            rgb = tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))
            _, lightness, _ = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            lightnesses.append(lightness)
        assert lightnesses == sorted(lightnesses)


def test_families_are_hue_ordered() -> None:
    palette = bucket_palette_into_families(_synthetic_64_colours())
    median_hues = []
    for family in palette.values():
        hues = []
        for hex_str in family.values():
            hex_str = hex_str.lstrip("#")
            rgb = tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))
            hue, _, _ = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            hues.append(hue)
        median_hues.append(sorted(hues)[len(hues) // 2])
    assert median_hues == sorted(median_hues)


def test_snap_to_palette_picks_true_nearest() -> None:
    palette = [(0, 0, 0), (100, 100, 100), (255, 255, 255)]
    assert snap_to_palette((103, 103, 103), palette) == (100, 100, 100)


def test_snap_to_palette_is_idempotent_on_exact_match() -> None:
    palette = [(10, 20, 30), (200, 150, 90)]
    assert snap_to_palette((200, 150, 90), palette) == (200, 150, 90)
