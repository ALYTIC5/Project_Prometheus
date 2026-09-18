"""World Track W0 -- import PixelLab character exports into the NEW
art/raw/ + art/registry.json contract (Quant Pantheon World Track,
supersedes Prompt 12's art/scaled/ + overrides.json pipeline for
everything built from here on).

Reuses art/characters/<folder>/metadata.json, which already exists on
disk (tools/art/import_pixellab.py, from the Prompt-12-era pipeline,
already extracted all 38 Mockups.zip characters into this exact shape) --
this script does NOT re-extract Mockups.zip a second time. It reads the
same PixelLab export schema (`group_id`, `states[].character{id,size,
view,directions,prompt,template_id}`, `states[].frames.{rotations,
animations}`) that import_pixellab.py already parses, and copies frames
into the NEW target layout:

    art/raw/characters/<key>/<state>/<anim>/<direction>/<frame>.png

`state` is `states[].folder` lowercased (e.g. "idle"); every current
export's rotations become a single anim called "rotation", frame 0
(matches W0's own wording: "Rotations become anim 'rotation', frame 0" --
`states[].frames.animations` is always `{}` today, per the 2026-09-14
DEPENDENCIES.md finding that these exports ship zero animation frames).
Idempotent: reruns overwrite the same destination paths, never append.

`key` is the character's folder name verbatim (e.g. "agent_scribe",
"hero_mage") -- semantic renaming (agent_scribe -> scribe, etc.) is
docs/ART_ROSTER.md's job (a mapping table), not this script's; the raw
layer stays traceable to its literal PixelLab export folder.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.art.common import ART, json_dump, load_rgba, save_rgba

CHARACTERS_DIR = ART / "characters"
RAW_CHARACTERS_DIR = ART / "raw" / "characters"
REGISTRY_PATH = ART / "registry.json"


def _ingest_character(folder: Path) -> list[dict[str, Any]]:
    """Copies one character's frames into art/raw/characters/<key>/... and
    returns one registry record per animation this character has (today,
    always exactly one: "rotation", 8 directions, 0 real animation
    frames)."""
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    key = folder.name
    records: list[dict[str, Any]] = []

    for state in metadata["states"]:
        character = state["character"]
        state_name = state["folder"].lower()
        rotations = state["frames"]["rotations"]
        animations = state["frames"]["animations"]

        directions: dict[str, str] = {}
        for direction, rel_path in rotations.items():
            src = folder / rel_path
            rgba = load_rgba(src)
            dest = RAW_CHARACTERS_DIR / key / state_name / "rotation" / direction / "0.png"
            save_rgba(rgba, dest)
            directions[direction] = str(dest.relative_to(ART.parent))

        if animations:
            # Not reachable today (every current export's animations dict
            # is empty -- W4 is what will eventually fill this in via
            # animate_character), but real if it ever is: copy each
            # animation's own frames the same way rather than silently
            # dropping them.
            for anim_name, anim_frames in animations.items():
                for direction, frame_paths in anim_frames.items():
                    for frame_idx, rel_path in enumerate(frame_paths):
                        src = folder / rel_path
                        rgba = load_rgba(src)
                        dest = (
                            RAW_CHARACTERS_DIR
                            / key
                            / state_name
                            / anim_name
                            / direction
                            / f"{frame_idx}.png"
                        )
                        save_rgba(rgba, dest)

        records.append(
            {
                "key": key,
                "kind": "character",
                "pixellab_id": character["id"],
                "source": "mockup",
                "prompt": character["prompt"],
                "size": character["size"],
                "directions": character["directions"],
                "state": state_name,
                "animations": {
                    "rotation": {
                        "directions": len(directions),
                        "frames": 1,
                        "status": "rotation_only",
                        "generations_spent": 0,
                        "job_ids": [],
                    }
                },
                "palette_locked": False,
                "created_at": character["created_at"],
            }
        )
    return records


def _load_existing_registry() -> dict[str, Any]:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--characters-dir", type=Path, default=CHARACTERS_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify every character folder has a metadata.json and every "
        "expected direction file exists on disk; write nothing.",
    )
    args = parser.parse_args()

    folders = sorted(
        p for p in args.characters_dir.iterdir() if (p / "metadata.json").exists()
    )
    if not folders:
        print(f"No character folders with metadata.json in {args.characters_dir}", file=sys.stderr)
        return 1

    if args.check:
        missing: list[str] = []
        for folder in folders:
            metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
            for state in metadata["states"]:
                for direction, rel_path in state["frames"]["rotations"].items():
                    if not (folder / rel_path).exists():
                        missing.append(f"{folder.name}/{state['folder']}/{direction}")
        if missing:
            print(f"MISSING {len(missing)} source frame(s):", file=sys.stderr)
            for m in missing:
                print(f"  {m}", file=sys.stderr)
            return 1
        print(f"OK: {len(folders)} character folders, all source frames present.")
        return 0

    registry = _load_existing_registry()
    all_records: list[dict[str, Any]] = []
    for folder in folders:
        all_records.extend(_ingest_character(folder))

    for record in all_records:
        registry[record["key"]] = record

    registry["_generated_at"] = datetime.now(UTC).isoformat()
    json_dump(registry, REGISTRY_PATH)

    print(f"Ingested {len(folders)} characters ({len(all_records)} state records) into:")
    print(f"  {RAW_CHARACTERS_DIR.relative_to(ART.parent)}")
    print(f"  {REGISTRY_PATH.relative_to(ART.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
