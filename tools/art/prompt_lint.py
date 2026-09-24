"""R1 (Greek Rebuild) - Theme Lock law T2/T3 enforcement.

lint(text) checks a composed PixelLab description against art/prompts.yaml's
banned-word list, required lexicon count, and max length. Every description
compose_prompt.compose() produces must pass this before it's ever sent to a
PixelLab tool call.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_PATH = REPO_ROOT / "art" / "prompts.yaml"

MIN_LEXICON_MATCHES = 2


@functools.lru_cache(maxsize=1)
def _load_prompts() -> dict:
    return yaml.safe_load(PROMPTS_PATH.read_text(encoding="utf-8"))


def _clear_cache() -> None:
    _load_prompts.cache_clear()


def _whole_word_pattern(phrase: str) -> re.Pattern[str]:
    # Phrases may contain spaces or hyphens ("hard hat", "3d render") -- treat
    # the whole phrase as the unit, bounded by non-word characters (or string
    # edges) on either side, not per-word \b (which would let "3d" inside
    # "3density" match "3d" -- not a real risk here, but boundary-correct
    # either way since every banned phrase is checked as one literal unit).
    return re.compile(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", re.IGNORECASE)


@dataclass
class LintResult:
    ok: bool
    banned_hits: list[str] = field(default_factory=list)
    lexicon_matches: list[str] = field(default_factory=list)
    length: int = 0
    max_length: int = 0
    errors: list[str] = field(default_factory=list)


def lint(text: str) -> LintResult:
    prompts = _load_prompts()
    banned: list[str] = prompts.get("banned", [])
    lexicon: list[str] = prompts.get("lexicon", [])
    helmet_exceptions: list[str] = prompts.get("helmet_exceptions", [])
    max_length: int = prompts.get("max_description_length", 900)

    errors: list[str] = []

    banned_hits: list[str] = []
    for phrase in banned:
        if _whole_word_pattern(phrase).search(text):
            banned_hits.append(phrase)

    # "helmet" alone is banned unless immediately preceded by an allowed
    # qualifier (checked as substrings before applying the ban).
    for match in re.finditer(r"(?<![\w-])helmet(?![\w-])", text, re.IGNORECASE):
        start = match.start()
        preceding = text[:start].rstrip().lower()
        if not any(preceding.endswith(exc) for exc in helmet_exceptions):
            banned_hits.append("helmet (unqualified)")

    if banned_hits:
        errors.append(f"banned word(s) found: {', '.join(sorted(set(banned_hits)))}")

    lexicon_matches = [word for word in lexicon if _whole_word_pattern(word).search(text)]
    if len(lexicon_matches) < MIN_LEXICON_MATCHES:
        errors.append(
            f"only {len(lexicon_matches)} lexicon word(s) matched "
            f"({lexicon_matches}), need at least {MIN_LEXICON_MATCHES}"
        )

    length = len(text)
    if length > max_length:
        errors.append(f"description is {length} chars, max is {max_length}")

    return LintResult(
        ok=not errors,
        banned_hits=sorted(set(banned_hits)),
        lexicon_matches=lexicon_matches,
        length=length,
        max_length=max_length,
        errors=errors,
    )


if __name__ == "__main__":
    import sys

    text = sys.stdin.read() if len(sys.argv) < 2 else sys.argv[1]
    result = lint(text)
    if result.ok:
        print(f"OK ({len(result.lexicon_matches)} lexicon matches, {result.length} chars)")
    else:
        for error in result.errors:
            print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
