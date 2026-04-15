import type { Metadata } from 'next';
import DesktopBridgeBootstrap from '@/components/DesktopBridgeBootstrap';
import { ThemeProvider } from '@/lib/ThemeContext';
import './globals.css';

export const metadata: Metadata = {
  title: 'WORLDVIEW // ORBITAL TRACKING',
  description: 'Advanced Geopolitical Risk Dashboard',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet" />
      </head>
      <body className="antialiased bg-[var(--bg-primary)]" suppressHydrationWarning>
        <ThemeProvider>
          <DesktopBridgeBootstrap />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
