"""R1 (Greek Rebuild) - the ONLY place PixelLab descriptions are built.

Reads art/theme.yaml (Greek names, footprints, canvas sizes, subject/detail
vocabulary) and art/prompts.yaml (style suffixes, templates) and composes a
single description string for a given asset key. Every generation call must
route its description through compose() -- never hand-write one into a tool
call (see tools/art/prompt_lint.py's own test that enforces this).

Category is inferred from which theme.yaml table the key is found in, so a
caller only ever needs the key itself (e.g. compose("library"),
compose("zeus"), compose("builder")).
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
THEME_PATH = REPO_ROOT / "art" / "theme.yaml"
PROMPTS_PATH = REPO_ROOT / "art" / "prompts.yaml"

# theme.yaml table name -> prompts.yaml template name -> style suffix key.
_CATEGORY_TEMPLATE = {
    "buildings": "building",
    "deities": "deity",
    "agents": "agent",
    "heroes": "hero",
    "townsfolk": "townsfolk",
}
_CATEGORY_STYLE_SUFFIX = {
    "buildings": "style_suffix_world",
    "deities": "style_suffix_character",
    "agents": "style_suffix_character",
    "heroes": "style_suffix_character",
    "townsfolk": "style_suffix_character",
}
# Building keys that are a god's temple, not a system building, use the
# "temple" template instead of "building" -- deities.yaml's own family keys
# double as god-temple theme.yaml building keys when a temple is generated
# per-family (R4). Not every deity has a temple.yaml entry of its own;
# `compose_temple(family)` covers those explicitly.


@functools.lru_cache(maxsize=1)
def _load_theme() -> dict[str, Any]:
    return yaml.safe_load(THEME_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _load_prompts() -> dict[str, Any]:
    return yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8"))


def _clear_cache() -> None:
    """Test-only: force theme.yaml/prompts.yaml to be re-read."""
    _load_theme.cache_clear()
    _load_prompts.cache_clear()


def _find_entry(key: str) -> tuple[str, dict[str, Any]]:
    theme = _load_theme()
    for category in _CATEGORY_TEMPLATE:
        table = theme.get(category, {})
        if key in table:
            return category, table[key]
    raise KeyError(f"{key!r} not found in any art/theme.yaml table")


def _format_details(details: list[str]) -> str:
    if not details:
        return ""
    if len(details) == 1:
        return details[0]
    return ", ".join(details[:-1]) + f", and {details[-1]}"


def compose(key: str) -> str:
    """Build the full PixelLab description for theme.yaml key `key`."""
    category, entry = _find_entry(key)
    prompts = _load_prompts()
    template_name = _CATEGORY_TEMPLATE[category]
    template = prompts["templates"][template_name]
    style_suffix = prompts[_CATEGORY_STYLE_SUFFIX[category]]
    return template.format(
        subject=entry["subject"],
        greek_name=entry["greek_name"],
        details=_format_details(entry.get("details", [])),
        style_suffix=style_suffix,
    ).strip()


def compose_temple(family_key: str) -> str:
    """Build the description for the TEMPLE building of deity `family_key`
    (a key in theme.yaml's `deities` table) -- distinct from the deity FIGURE
    itself, which `compose(family_key)` already builds via the "deity"
    template."""
    theme = _load_theme()
    prompts = _load_prompts()
    entry = theme["deities"][family_key]
    template = prompts["templates"]["temple"]
    return template.format(
        subject=f"a Doric temple shrine dedicated to {entry['greek_name']}",
        greek_name=entry["greek_name"],
        details=_format_details(entry.get("details", [])),
        style_suffix=prompts["style_suffix_world"],
    ).strip()


def resolve_hero_fold(archetype: str) -> str:
    """theme.yaml's own hero_fold mapping: an archetype not yet released
    folds onto one of the four released heroes. Returns the archetype
    unchanged if it's already a released hero key."""
    theme = _load_theme()
    if archetype in theme["heroes"]:
        return archetype
    fold = theme.get("hero_fold", {})
    if archetype in fold:
        return fold[archetype]
    raise KeyError(f"{archetype!r} is not a released hero and has no hero_fold entry")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m tools.art.compose_prompt <theme.yaml key>", file=sys.stderr)
        raise SystemExit(1)
    print(compose(sys.argv[1]))
