"""A0-characters - import PixelLab character exports into the art pipeline.

Reads art/characters/<name>/metadata.json (a PixelLab export: `group_id`,
`states[].character{id,size,view,directions}`, `states[].frames.rotations`)
and registers each of its 8-direction PNGs into the same
art/scaled/<name>.png + art/sliced/overrides.json contract that
normalize_scale.py's output already feeds to compute_anchors.py and
pack_atlas.py -- so those two stages need zero changes to pick these up.

No alpha recovery, no rescaling, no quantization here: these assets are
already clean RGBA with binary alpha (verified against the source PNGs),
unlike the recovered-JPEG sprites this pipeline was originally built for.
Iterates every `states[]` entry (not just "Idle") so a later PixelLab
export that fills in "animations" (currently always `{}`) is picked up
without changing this file.

Manifest naming:
  - `agent_<role>` folders (the 4-12 workers with real building anchors)
    drop the `agent_` prefix so the key becomes `<role>_<action>_r<n>`,
    matching resolveAgentSprite()'s existing `${role}_${action}_r${rotation}`
    contract in frontend/src/sprites/registry.ts exactly.
  - every other folder (heroes, gods, harbour NPCs, named world figures)
    keeps its full folder name: `<name>_<action>_r<n>`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.art.common import ART, OVERRIDES_PATH, json_dump, load_rgba, read_overrides, save_rgba

CHARACTERS_DIR = ART / "characters"
SCALED_DIR = ART / "scaled"

# PixelLab's own compass order -> rotation index. This is the one contract
# frontend/src/sprites/direction.ts must mirror exactly.
ROTATION_INDEX: dict[str, int] = {
    "south": 0,
    "south-east": 1,
    "east": 2,
    "north-east": 3,
    "north": 4,
    "north-west": 5,
    "west": 6,
    "south-west": 7,
}

PROVENANCE_PREFIX = "pixellab_"


def _base_name(folder_name: str) -> str:
    if folder_name.startswith("agent_"):
        return folder_name[len("agent_") :]
    return folder_name


def _import_character(folder: Path) -> list[dict]:
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    base_name = _base_name(folder.name)
    records: list[dict] = []

    for state in metadata["states"]:
        character = state["character"]
        action = state["folder"].lower()
        rotations = state["frames"]["rotations"]
        missing = ROTATION_INDEX.keys() - rotations.keys()
        if missing:
            print(
                f"FATAL: {folder.name} state {action!r} missing rotations {sorted(missing)}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        for direction, rel_path in rotations.items():
            idx = ROTATION_INDEX[direction]
            name = f"{base_name}_{action}_r{idx}"
            src = folder / rel_path
            rgba = load_rgba(src)
            dest = SCALED_DIR / f"{name}.png"
            save_rgba(rgba, dest)
            records.append(
                {
                    "character_folder": folder.name,
                    "character_id": character["id"],
                    "base_name": base_name,
                    "action": action,
                    "direction": direction,
                    "rotation_index": idx,
                    "name": name,
                    "size": character["size"],
                    "source": str(src.relative_to(ART.parent)),
                    "scaled_path": str(dest.relative_to(ART.parent)),
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--characters-dir", type=Path, default=CHARACTERS_DIR)
    args = parser.parse_args()

    folders = sorted(p for p in args.characters_dir.iterdir() if (p / "metadata.json").exists())
    if not folders:
        print(f"No character folders with metadata.json in {args.characters_dir}", file=sys.stderr)
        return 1

    all_records: list[dict] = []
    for folder in folders:
        all_records.extend(_import_character(folder))

    overrides = read_overrides()
    # Machine-managed provenance: drop any stale pixellab_* entry from a
    # previous run (a renamed/removed character) rather than accumulating
    # dead ids forever -- unlike the hand-named JPEG slices this pipeline
    # was built for, nothing here is ever human-edited.
    overrides = {k: v for k, v in overrides.items() if not k.startswith(PROVENANCE_PREFIX)}
    for record in all_records:
        sprite_id = f"{PROVENANCE_PREFIX}{record['name']}"
        overrides[sprite_id] = {
            "name": record["name"],
            "anchor": None,
            "anchor_source": None,
            "notes": f"pixellab:{record['character_id']}",
            "stale": False,
        }
    json_dump(overrides, OVERRIDES_PATH)

    json_dump(all_records, ART / "characters_index.json")

    characters = {r["character_folder"] for r in all_records}
    print(f"Imported {len(characters)} characters, {len(all_records)} frames.")
    print(f"Registered into {OVERRIDES_PATH} -- run `make art-build` next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
