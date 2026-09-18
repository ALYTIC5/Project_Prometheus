# Art Decisions — World Track

Records irreversible or costly art-pipeline choices so later batches don't
re-litigate them or re-spend PixelLab generations answering the same
question twice.

## W4 pilot: walk-cycle mode (template vs v3) — 2026-09-18

**Question:** for every future character's walk animation, use PixelLab's
templated `animate_character(template_animation_id="walking-8-frames")`
(1 generation/direction, fixed 8-frame gait) or custom
`animate_character(mode="v3", action_description=..., frame_count=...)`
(cost scales with canvas x frame_count, but in practice also worked out to
1 generation for this character's 48x48 canvas / 8-frame request — so at
this size the two modes are cost-equivalent per direction, not a
budget tradeoff)?

**Pilot:** ran both on `agent_scribe` (real, still-existing account
character — see `docs/ART_ROSTER.md`), all 8 directions via template,
one direction (south-east) via v3, same `frame_count=8`. Comparison sheet:
`artifacts/art/walk_pilot_comparison.png` (gitignored, regenerate via the
job IDs recorded in `art/registry.json`'s `agent_scribe.animations`).

**Findings (south-east, visually inspected against the rotation reference):**
- **Identity:** template preserved the held item (the sealed scroll, the
  character's defining "Scribe" prop per its PixelLab prompt) exactly
  across all 8 frames. v3 drifted the held item toward a dagger/blade
  shape in several frames — a real identity break, not a rendering
  artifact, since the rotation reference and template output both agree
  on "scroll" and only v3 disagrees.
- **Leg articulation:** template's stride is very subtle — frame-to-frame
  leg position barely changes; the walk reads mostly as the scroll arm
  swinging, not as leg motion. v3 showed clearly alternating leg/knee
  position across frames — a more legible "walking" gait.
- **No clipping** at the 48px canvas edge in either mode. No visible
  loop-seam break in the 8-frame cycles (frame 7/8 returns close to
  frame 0's pose in both).

**Decision: use v3 mode for future walk cycles, with the action
description made prop-explicit** (e.g. "walking at a steady pace,
carrying a sealed scroll, no weapon" instead of the generic "walking at a
steady pace" used in this pilot). Reasoning:
- Cost is a wash at this canvas/frame-count (1 gen/direction either way),
  so the decision is quality-only.
- Law W2 requires signal-bearing motion (agents bound to jobs) to be
  legible as motion — a walk cycle that's mostly a static pose with a
  swinging prop fails that bar more than an identity slip that a tighter
  prompt can prevent for free (no extra generation cost, just better
  wording on the same call).
- The identity-drift fix is a prompt change, not a re-generation cost;
  the leg-articulation weakness in template mode has no equivalent free
  fix (it's the template's fixed animation data, not something a prompt
  parameter controls).

**Caveat for future batches:** verify the prop-explicit prompt actually
holds before spending a full 8-direction batch on a character — if v3
still drifts the held item with explicit wording in the prompt, fall back
to template mode for that specific character rather than spending
generations on repeated corrective attempts.
