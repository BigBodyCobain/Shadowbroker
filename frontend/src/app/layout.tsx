import type { Metadata } from 'next';
import localFont from 'next/font/local';
import DesktopBridgeBootstrap from '@/components/DesktopBridgeBootstrap';
import MotionRoot from '@/components/MotionRoot';
import { ThemeProvider } from '@/lib/ThemeContext';
import { I18nProvider } from '@/i18n';
import './globals.css';

const jetBrainsMono = localFont({
  src: [
    { path: './fonts/JetBrainsMono-Regular.woff2', weight: '400', style: 'normal' },
    { path: './fonts/JetBrainsMono-Bold.woff2', weight: '700', style: 'normal' },
  ],
  display: 'swap',
  variable: '--font-jetbrains-mono',
});

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
      <body className={`${jetBrainsMono.variable} antialiased bg-[var(--bg-primary)]`} suppressHydrationWarning>
        <I18nProvider>
          <ThemeProvider>
            <MotionRoot>
              <DesktopBridgeBootstrap />
              {children}
            </MotionRoot>
          </ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
