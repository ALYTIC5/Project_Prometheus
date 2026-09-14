"""tools/art/common.py's palette family/shade bucketing (A5) and
nearest-colour snap -- the direct guard on palette.ts's structural
contract (exactly 4 shades per family: dark/mid/light/highlight).
"""
from __future__ import annotations

import colorsys

import pytest

from tools.art.build_palette import lift_lightness_and_saturation
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


def _lightness_of(rgb: tuple[int, int, int]) -> float:
    _, lightness, _ = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return lightness


def test_lift_maps_darkest_and_brightest_to_floor_and_ceiling() -> None:
    # A dark, muddy source palette -- everything under L~0.3, like the
    # measured recovered-JPEG art this transform exists to fix.
    lightness_values = (0.05, 0.15, 0.25, 0.29)
    dark_palette = [colorsys.hls_to_rgb(0.4, lightness, 0.5) for lightness in lightness_values]
    dark_palette = [(round(r * 255), round(g * 255), round(b * 255)) for r, g, b in dark_palette]

    lifted, report = lift_lightness_and_saturation(dark_palette, floor=0.18, ceiling=0.88)

    lightnesses = [_lightness_of(rgb) for rgb in lifted]
    assert min(lightnesses) == pytest.approx(0.18, abs=3e-3)
    assert max(lightnesses) == pytest.approx(0.88, abs=3e-3)
    assert report["lightness_before"]["min"] == pytest.approx(0.05, abs=0.01)


def test_lift_preserves_hue() -> None:
    palette = [colorsys.hls_to_rgb(h, 0.3, 0.5) for h in (0.0, 0.25, 0.5, 0.75)]
    palette = [(round(r * 255), round(g * 255), round(b * 255)) for r, g, b in palette]
    lifted, _ = lift_lightness_and_saturation(palette)
    for (r, g, b), (lr, lg, lb) in zip(palette, lifted, strict=False):
        original_hue, _, _ = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        lifted_hue, _, _ = colorsys.rgb_to_hls(lr / 255, lg / 255, lb / 255)
        assert abs(original_hue - lifted_hue) < 0.01


def test_lift_saturation_boost_is_capped_at_one() -> None:
    palette = [(round(0.9 * 255), round(0.1 * 255), round(0.1 * 255))]  # already highly saturated
    lifted, _ = lift_lightness_and_saturation(palette, saturation_boost=2.0)
    _, _, sat = colorsys.rgb_to_hls(*(c / 255 for c in lifted[0]))
    assert sat <= 1.0


def test_lift_is_a_no_op_when_palette_is_a_single_flat_colour() -> None:
    # span == 0 guard: must not divide by zero.
    palette = [(120, 120, 120)] * 4
    lifted, report = lift_lightness_and_saturation(palette, floor=0.18, ceiling=0.88)
    assert len(lifted) == 4
    for rgb in lifted:
        assert _lightness_of(rgb) == pytest.approx((0.18 + 0.88) / 2, abs=0.01)
