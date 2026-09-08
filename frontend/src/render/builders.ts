import * as PIXI from 'pixi.js';
import { Layer, depthOf, gridToScreen } from '../iso/projection';
import type { Building } from '../types';

const MAX_BUILDERS = 12;
type Activity = 'hammer' | 'measure' | 'carry';
const ACTIVITIES: Activity[] = ['hammer', 'measure', 'carry'];

function activityFor(buildingId: string): Activity {
  let hash = 0;
  for (let i = 0; i < buildingId.length; i++) hash = (hash * 31 + buildingId.charCodeAt(i)) | 0;
  return ACTIVITIES[Math.abs(hash) % ACTIVITIES.length];
}

function drawBuilder(activity: Activity): PIXI.Container {
  const c = new PIXI.Container();
  const g = new PIXI.Graphics();
  // Yellow hard-hat figure (PROMPTS.md: "builder sprites are yellow
  // hard-hat figures") -- body, head, hat.
  g.rect(-3, -10, 6, 10).fill({ color: 0x2c3e50 });
  g.circle(0, -13, 4).fill({ color: 0xe8b98a });
  g.arc(0, -15, 4.5, Math.PI, 0).fill({ color: 0xf1c40f });
  if (activity === 'hammer') {
    g.moveTo(3, -8).lineTo(9, -12).stroke({ color: 0x7f5539, width: 2 });
    g.rect(8, -14, 4, 3).fill({ color: 0x888888 });
  } else if (activity === 'measure') {
    g.moveTo(-3, -6).lineTo(-9, 0).stroke({ color: 0xcccc88, width: 1.5 });
  } else {
    g.rect(-8, -9, 5, 5).fill({ color: 0x966f4d });
  }
  c.addChild(g);
  return c;
}

export interface BuildersHandle {
  container: PIXI.Container;
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
  const container = new PIXI.Container();
  const bobbers: PIXI.Container[] = [];

  const eligible = buildings
    .filter((b) => {
      const phase = b.phase.toUpperCase();
      return phase === 'SCAFFOLDING' || phase === 'FOUNDATION';
    })
    .slice(0, MAX_BUILDERS);

  for (const building of eligible) {
    const activity = activityFor(building.id);
    const figure = drawBuilder(activity);
    const edgeX = building.location.x + building.location.width * 0.75;
    const edgeY = building.location.y + building.location.height * 0.75;
    const { x, y } = gridToScreen(edgeX, edgeY);
    figure.x = x;
    figure.y = y;
    figure.zIndex = depthOf(edgeX, edgeY, 1, 1, Layer.AGENT);
    (figure as PIXI.Container & { __baseY: number }).__baseY = y;
    container.addChild(figure);
    bobbers.push(figure);
  }

  function update(elapsedMs: number): void {
    for (let i = 0; i < bobbers.length; i++) {
      const figure = bobbers[i] as PIXI.Container & { __baseY: number };
      figure.y = figure.__baseY + Math.sin(elapsedMs / 250 + i) * 1.5;
    }
  }

  return { container, update };
}
