"""R1 (Greek Rebuild): compose_prompt + prompt_lint + check_asset.

Theme Lock law T2 ("every PixelLab description is composed by
tools/art/compose_prompt.py ... and must pass tools/art/prompt_lint.py")
is what this file verifies, plus T3's check_asset validator.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.art import check_asset as check_asset_mod
from tools.art import compose_prompt, prompt_lint

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_yaml_cache():
    compose_prompt._clear_cache()
    prompt_lint._clear_cache()
    yield
    compose_prompt._clear_cache()
    prompt_lint._clear_cache()


# --------------------------------------------------------------------------
# prompt_lint
# --------------------------------------------------------------------------


def test_old_medieval_builder_prompt_fails_lint():
    old_prompt = (
        "Sturdy fantasy builder agent in a leather work apron, carrying a "
        "wooden mallet and a rolled blueprint, constructing scaffolding at "
        "the Forge"
    )
    result = prompt_lint.lint(old_prompt)
    assert not result.ok
    # No Greek lexicon words at all in the old prompt -- fails on that alone.
    assert any("lexicon" in e for e in result.errors)


def test_banned_word_is_rejected():
    text = "A marble temple with a medieval castle tower and bronze doors, olive trees nearby."
    result = prompt_lint.lint(text)
    assert not result.ok
    assert "medieval" in result.banned_hits
    assert "castle" in result.banned_hits


def test_helmet_alone_is_banned_but_qualified_helmet_is_allowed():
    bad = "A warrior wearing a helmet, holding a marble shield, olive branch in hand."
    good = (
        "A warrior wearing a bronze crested helmet, holding a marble shield, "
        "olive branch in hand."
    )
    assert not prompt_lint.lint(bad).ok
    assert prompt_lint.lint(good).ok


def test_too_few_lexicon_words_fails():
    text = "A warrior wearing bronze armor, standing in a field."
    result = prompt_lint.lint(text)
    assert not result.ok
    assert len(result.lexicon_matches) < prompt_lint.MIN_LEXICON_MATCHES


def test_valid_greek_description_passes():
    text = (
        "A stone temple with Doric marble columns and a terracotta roof, "
        "bronze doors, and olive trees growing nearby."
    )
    result = prompt_lint.lint(text)
    assert result.ok, result.errors


# --------------------------------------------------------------------------
# compose_prompt
# --------------------------------------------------------------------------


def test_every_theme_entry_composes_and_passes_lint():
    theme = compose_prompt._load_theme()
    checked = 0
    for category in ("buildings", "deities", "agents", "heroes", "townsfolk"):
        for key in theme[category]:
            text = compose_prompt.compose(key)
            result = prompt_lint.lint(text)
            assert result.ok, f"{category}/{key} failed lint: {result.errors}\n{text}"
            checked += 1
    assert checked > 20  # sanity: the tables are actually populated


def test_compose_unknown_key_raises():
    with pytest.raises(KeyError):
        compose_prompt.compose("this_key_does_not_exist")


def test_compose_temple_for_every_deity():
    theme = compose_prompt._load_theme()
    for family_key in theme["deities"]:
        text = compose_prompt.compose_temple(family_key)
        result = prompt_lint.lint(text)
        assert result.ok, f"temple for {family_key} failed lint: {result.errors}"


def test_hero_fold_resolves_unreleased_archetypes():
    assert compose_prompt.resolve_hero_fold("rogue") == "fast"
    assert compose_prompt.resolve_hero_fold("alchemist") == "mage"
    assert compose_prompt.resolve_hero_fold("hybrid") == "duelist"
    # An already-released hero resolves to itself.
    assert compose_prompt.resolve_hero_fold("tank") == "tank"


def test_hero_fold_unknown_archetype_raises():
    with pytest.raises(KeyError):
        compose_prompt.resolve_hero_fold("not_a_real_archetype")


def test_no_hand_written_pixellab_descriptions_outside_compose_prompt():
    """Theme Lock law T2: nothing under tools/ or frontend/src/world/ may
    contain a literal, long hand-written description string passed to a
    PixelLab-shaped call. Heuristic: no file other than compose_prompt.py/
    prompts.yaml/theme.yaml contains the phrase "isometric pixel-art" (the
    style-suffix marker every real description ends with) as a quoted
    string literal."""
    marker = "isometric pixel-art"
    allowed = {
        REPO_ROOT / "tools" / "art" / "compose_prompt.py",
        REPO_ROOT / "art" / "prompts.yaml",
        Path(__file__).resolve(),  # this test file quotes examples
    }
    offenders = []
    for base in (REPO_ROOT / "tools", REPO_ROOT / "frontend" / "src" / "world"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path in allowed or not path.is_file():
                continue
            if path.suffix not in (".py", ".ts", ".tsx", ".json", ".yaml", ".yml"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if marker in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"hand-written PixelLab descriptions found in: {offenders}"


# --------------------------------------------------------------------------
# check_asset
# --------------------------------------------------------------------------


def _make_png(
    tmp_path: Path, size: tuple[int, int], opaque_box: tuple[int, int, int, int] | None
) -> Path:
    arr = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    if opaque_box is not None:
        x0, y0, x1, y1 = opaque_box
        arr[y0:y1, x0:x1] = [255, 0, 0, 255]
    path = tmp_path / "test.png"
    Image.fromarray(arr, "RGBA").save(path)
    return path


def test_check_asset_correct_size_and_centered_content(tmp_path: Path):
    path = _make_png(tmp_path, (68, 68), opaque_box=(10, 10, 58, 58))
    result = check_asset_mod.check_asset(path, requested_size=68)
    assert result.ok, result.errors
    assert result.size_matches
    assert not result.clipped_edges


def test_check_asset_size_mismatch_is_detected(tmp_path: Path):
    path = _make_png(tmp_path, (96, 96), opaque_box=(10, 10, 86, 86))
    result = check_asset_mod.check_asset(path, requested_size=68)
    assert not result.ok
    assert not result.size_matches
    assert result.actual_size == (96, 96)


def test_check_asset_detects_edge_clipping(tmp_path: Path):
    path = _make_png(tmp_path, (68, 68), opaque_box=(0, 10, 58, 58))
    result = check_asset_mod.check_asset(path, requested_size=68)
    assert not result.ok
    assert "left" in result.clipped_edges


def test_check_asset_flags_empty_image(tmp_path: Path):
    path = _make_png(tmp_path, (68, 68), opaque_box=None)
    result = check_asset_mod.check_asset(path, requested_size=68)
    assert not result.ok
    assert result.is_empty
