import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import { PALETTE } from '../sprites/palette';
import { hashString } from '../sprites/registry';
import type { Building } from '../types';

const MAX_BUILDERS = 12;
const SCALE = 3;
const FRAME_COUNT = 8;
const FRAME_DURATION_MS = 120;
const OUTLINE = 0x000000;

type Activity = 'hammer' | 'measure' | 'carry';
const ACTIVITIES: Activity[] = ['hammer', 'measure', 'carry'];

function activityFor(buildingId: string): Activity {
  return ACTIVITIES[hashString(buildingId) % ACTIVITIES.length];
}

/** Role -> palette family, mirroring the intent (not the exact hex) of
 * prometheus/world/construction.py's ROLE_COLORS. */
const ROLE_FAMILY: Record<string, string> = {
  builder: 'orange',
  scribe: 'blue',
  engineer: 'orange',
  experimenter: 'yellow',
  statistician: 'purple',
  guardian: 'red',
  auditor: 'stone',
  necromancer: 'red',
  scholar: 'stone',
  prophet: 'purple',
};

function hatColorFor(role: string | undefined): number {
  const family = ROLE_FAMILY[role ?? ''] ?? 'yellow';
  return PALETTE[`${family}.light`] ?? PALETTE['yellow.light'];
}

function drawBody(hatColor: number): PIXI.Graphics {
  const g = new PIXI.Graphics();
  g.rect(-3, -10, 6, 10).fill({ color: 0x2c3e50 }).stroke({ color: OUTLINE, width: 0.5 });
  g.circle(0, -13, 4).fill({ color: 0xe8b98a }).stroke({ color: OUTLINE, width: 0.5 });
  g.arc(0, -15, 4.5, Math.PI, 0).fill({ color: hatColor }).stroke({ color: OUTLINE, width: 0.5 });
  return g;
}

/** Redraws just the tool/arm for one 8-frame work-animation cycle,
 * advanced on elapsed time (not distance -- these builders don't move, so
 * there is no distance to advance on; PROMPTS.md itself treats idle/work
 * animation as cosmetic and time-based-safe, unlike a walk cycle). */
function drawTool(g: PIXI.Graphics, activity: Activity, frame: number): boolean {
  g.clear();
  const swing = Math.sin((frame / FRAME_COUNT) * Math.PI * 2);
  if (activity === 'hammer') {
    const armX = 3 + swing * 3;
    const armY = -8 - swing * 4;
    g.moveTo(3, -8).lineTo(armX + 6, armY).stroke({ color: 0x7f5539, width: 2 }).stroke({ color: OUTLINE, width: 0.5 });
    g.rect(armX + 5, armY - 2, 4, 3).fill({ color: 0x888888 }).stroke({ color: OUTLINE, width: 0.5 });
    return swing < -0.6; // downstroke -- caller spawns a dust puff
  } else if (activity === 'measure') {
    const armX = -3 - swing * 2;
    g.moveTo(-3, -6).lineTo(armX - 6, swing * 2).stroke({ color: 0xcccc88, width: 1.5 });
  } else {
    g.rect(-8, -9 + swing, 5, 5).fill({ color: 0x966f4d }).stroke({ color: OUTLINE, width: 0.5 });
  }
  return false;
}

function drawDustPuff(): PIXI.Graphics {
  const g = new PIXI.Graphics();
  g.circle(8, -2, 2).fill({ color: 0xcbb896, alpha: 0.5 });
  g.circle(11, -3, 1.5).fill({ color: 0xcbb896, alpha: 0.35 });
  return g;
}

export interface BuildersHandle {
  /** Each builder is its own root, meant to be added directly to the
   * shared sortableChildren entities layer (render/building.ts's parent)
   * -- NOT wrapped in one container, which would make all builders stack
   * as a single unit against buildings instead of competing individually
   * on real zIndex (the same layering bug the ground-plane fix removed,
   * one level up). */
  roots: PIXI.Container[];
  update: (elapsedMs: number) => void;
}

/** Static idle-decoration builders on real SCAFFOLDING/FOUNDATION
 * buildings only -- no from/to location, no pathfinding, no per-agent
 * identity persisted anywhere. Recomputed fresh from `buildings` every
 * redraw, exactly like every other render layer. This is the actual
 * PROMPTS.md Prompt-1 spec ("builder sprites... idle animations"), not
 * the Prompt-4 job-driven migration system, which needs backend data
 * that does not exist yet (see docs/DEPENDENCIES.md). */
export function createBuilders(buildings: Building[]): BuildersHandle {
  const figures: { root: PIXI.Container; tool: PIXI.Graphics; activity: Activity; baseY: number; dust: PIXI.Graphics | null }[] = [];

  const eligible = buildings
    .filter((b) => {
      const phase = b.phase.toUpperCase();
      return phase === 'SCAFFOLDING' || phase === 'FOUNDATION';
    })
    .slice(0, MAX_BUILDERS);

  for (const building of eligible) {
    const activity = activityFor(building.id);
    const hatColor = hatColorFor(building.agent_roles[0]);
    const root = new PIXI.Container();
    root.scale.set(SCALE);
    root.addChild(drawBody(hatColor));
    const tool = new PIXI.Graphics();
    root.addChild(tool);

    const edgeX = building.location.x + building.location.width * 0.75;
    const edgeY = building.location.y + building.location.height * 0.75;
    const { x, y } = gridToScreen(edgeX, edgeY);
    root.x = x;
    root.y = y;
    root.zIndex = depthOf(edgeX, edgeY, 1, 1, Layer.AGENT);
    figures.push({ root, tool, activity, baseY: root.y, dust: null });
  }

  function update(elapsedMs: number): void {
    const frame = Math.floor(elapsedMs / FRAME_DURATION_MS) % FRAME_COUNT;
    for (let i = 0; i < figures.length; i++) {
      const f = figures[i];
      f.root.y = f.baseY + Math.sin(elapsedMs / 250 + i) * 0.5;
      const spawnDust = drawTool(f.tool, f.activity, frame);
      if (spawnDust && !f.dust) {
        f.dust = drawDustPuff();
        f.root.addChild(f.dust);
      } else if (!spawnDust && f.dust) {
        f.root.removeChild(f.dust);
        f.dust = null;
      }
    }
  }

  return { roots: figures.map((f) => f.root), update };
}
