import type { Metadata } from 'next';
import DesktopBridgeBootstrap from '@/components/DesktopBridgeBootstrap';
import { ThemeProvider } from '@/lib/ThemeContext';
import { I18nProvider } from '@/i18n';
import './globals.css';

export const metadata: Metadata = {
  title: 'WORLDVIEW // ORBITAL TRACKING',
  description: 'Advanced Geopolitical Risk Dashboard',
};

// The dashboard is a live local runtime, not a static landing page. If Next
// prerenders and caches the initial shell, Docker users can get stuck on the
// "prioritizing map feeds" markup before client polling ever hydrates.
export const dynamic = 'force-dynamic';
export const revalidate = 0;

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
        <I18nProvider>
          <ThemeProvider>
            <DesktopBridgeBootstrap />
            {children}
          </ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
