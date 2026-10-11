import './globals.css';

export const metadata = {
  title: 'Env-AI-Ron Dashboard',
  description: 'Nature-Centred AI planning dashboard for urban ecological intelligence.'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
