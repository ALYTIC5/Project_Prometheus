import manifest from '../../src/world/sprites/manifest.production.json';

export const metadata = {
  title: 'Sprite Roster — Project Prometheus',
};

const COMPASS = ['south', 'south-east', 'east', 'north-east', 'north', 'north-west', 'west', 'south-west'];
const ROTATION_KEY = /^(.+)_r([0-7])$/;

interface ManifestEntry {
  atlas?: string;
  frame?: { x: number; y: number; width: number; height: number };
}

/** Dev-only roster of every imported PixelLab character, straight from the
 * production atlas -- bypasses SPRITE_SET entirely (unlike the main world
 * view) since its whole purpose is inspecting the real art regardless of
 * mode. Answers "are they live?" at a glance and doubles as the visual
 * check that import_pixellab.py's anchors and pack_atlas.py's frame rects
 * are correct: feet should sit on each cell's baseline, all 8 rotations
 * should look like the same character turning in place. */
export default function SpriteRosterPage() {
  const entries = manifest as Record<string, ManifestEntry>;
  const byCharacter = new Map<string, (ManifestEntry | undefined)[]>();

  for (const [key, entry] of Object.entries(entries)) {
    const m = ROTATION_KEY.exec(key);
    if (!m || !entry.atlas?.includes('characters')) continue;
    const [, base, rot] = m;
    const frames = byCharacter.get(base) ?? new Array<ManifestEntry | undefined>(8).fill(undefined);
    frames[Number(rot)] = entry;
    byCharacter.set(base, frames);
  }

  const characters = Array.from(byCharacter.keys()).sort();

  return (
    <div style={{ height: '100vh', overflowY: 'auto', background: '#0a0a1a', color: '#eee', fontFamily: 'monospace', padding: 24 }}>
      <h1 style={{ marginTop: 0 }}>Sprite Roster</h1>
      <p style={{ color: '#888' }}>
        {characters.length} characters x 8 rotations, straight from characters_atlas.png.
        Feet should land on each cell&apos;s baseline; missing frames render as a red gap.
      </p>
      {characters.map((base) => (
        <section key={base} style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 14, color: '#4A90D9', marginBottom: 8 }}>{base}</h2>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {byCharacter.get(base)!.map((entry, rotation) => (
              <figure key={rotation} style={{ margin: 0, textAlign: 'center' }}>
                <div
                  style={{
                    width: entry?.frame?.width ?? 48,
                    height: entry?.frame?.height ?? 48,
                    background: entry?.frame
                      ? `url(/sprites/${entry.atlas}) -${entry.frame.x}px -${entry.frame.y}px`
                      : '#500',
                    imageRendering: 'pixelated',
                    outline: '1px solid #222',
                  }}
                />
                <figcaption style={{ fontSize: 9, color: '#666' }}>{COMPASS[rotation]}</figcaption>
              </figure>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
