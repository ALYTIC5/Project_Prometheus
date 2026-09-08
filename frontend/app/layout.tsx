export const metadata = {
  title: 'Project Prometheus',
  description: 'A quantitative research and paper-trading laboratory, rendered as a living world.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, background: '#0a0a1a', overflow: 'hidden' }}>{children}</body>
    </html>
  );
}
