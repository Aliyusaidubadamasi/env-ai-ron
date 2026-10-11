import './globals.css';

export const metadata = {
  title: 'Community Monitor',
  description: 'Low-bandwidth community ecological monitoring interface.'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
