import type { Metadata } from 'next';
import { JetBrains_Mono } from 'next/font/google';
import DesktopBridgeBootstrap from '@/components/DesktopBridgeBootstrap';
import MotionRoot from '@/components/MotionRoot';
import { ThemeProvider } from '@/lib/ThemeContext';
import { I18nProvider } from '@/i18n';
import './globals.css';

const jetBrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '700'],
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
