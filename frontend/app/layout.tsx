export const metadata = {
  title: 'Project Prometheus',
  description: 'A quantitative research and paper-trading laboratory, rendered as a living world.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // Sets the window global sprites/registry.ts reads to pick ProceduralSpec
  // vs. AtlasSpec (PROMPTS.md: "add an env flag SPRITE_SET=placeholder
  // |production"). Inlined so it runs before any renderer code, and reads
  // process.env directly (not a client component) so Next.js still inlines
  // NEXT_PUBLIC_SPRITE_SET as a build-time constant.
  const spriteSet = process.env.NEXT_PUBLIC_SPRITE_SET ?? 'placeholder';
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#0a0a1a', overflow: 'hidden' }}>
        <script
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: `window.__SPRITE_SET__ = ${JSON.stringify(spriteSet)};` }}
        />
        {children}
      </body>
    </html>
  );
}
