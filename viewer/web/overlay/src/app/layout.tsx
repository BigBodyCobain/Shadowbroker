import type { Metadata } from 'next';
import localFont from 'next/font/local';
import MotionRoot from '@/components/MotionRoot';
import { ThemeProvider } from '@/lib/ThemeContext';
import { I18nProvider } from '@/i18n';
import { VIEWER_CHAT, VIEWER_CONNECT_HOSTS, VIEWER_DATA_BASE } from '@/viewer/config';
import './globals.css';

const jetBrainsMono = localFont({
  src: [
    { path: './fonts/JetBrainsMono-Regular.woff2', weight: '400', style: 'normal' },
    { path: './fonts/JetBrainsMono-Bold.woff2', weight: '700', style: 'normal' },
  ],
  display: 'swap',
  variable: '--font-jetbrains-mono',
});

const chakraPetch = localFont({
  src: [
    { path: './fonts/chakra-petch-latin-500-normal.woff2', weight: '500', style: 'normal' },
    { path: './fonts/chakra-petch-latin-600-normal.woff2', weight: '600', style: 'normal' },
    { path: './fonts/chakra-petch-latin-700-normal.woff2', weight: '700', style: 'normal' },
  ],
  display: 'swap',
  variable: '--font-chakra',
});

const inter = localFont({
  src: [{ path: './fonts/inter-latin-wght-normal.woff2', weight: '100 900', style: 'normal' }],
  display: 'swap',
  variable: '--font-inter',
});

export const metadata: Metadata = {
  title: 'ShadowBroker — Live Public Viewer',
  description: 'A look-only live map of public aircraft, ship, satellite and incident data from ShadowBroker.',
};

/**
 * The browser-enforced half of the viewer's network rule (netGuard.ts is the
 * other half). A static host cannot send headers, so the policy rides in a
 * meta tag. It lists the same hosts as VIEWER_CONNECT_HOSTS plus the data
 * host, forbids forms, frames and plugins, and never allows eval.
 */
function contentSecurityPolicy(): string {
  const dataOrigin = /^https?:\/\//i.test(VIEWER_DATA_BASE) ? new URL(VIEWER_DATA_BASE).origin : '';
  const chatOrigin = VIEWER_CHAT.url ? new URL(VIEWER_CHAT.url).origin : '';
  const connect = ["'self'", dataOrigin, chatOrigin, ...VIEWER_CONNECT_HOSTS.map((host) => `https://${host}`)].filter(
    Boolean,
  );
  return [
    "default-src 'self'",
    // Next's static export boots from small inline scripts.
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self' data:",
    `connect-src ${connect.join(' ')}`,
    "worker-src 'self' blob:",
    // Camera clips play straight from the camera's own https address.
    "media-src 'self' blob: https:",
    "frame-src 'none'",
    "object-src 'none'",
    "form-action 'none'",
    "base-uri 'self'",
  ].join('; ');
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <meta httpEquiv="Content-Security-Policy" content={contentSecurityPolicy()} />
        <meta name="referrer" content="no-referrer" />
      </head>
      <body
        className={`${jetBrainsMono.variable} ${chakraPetch.variable} ${inter.variable} antialiased bg-[var(--bg-primary)]`}
        suppressHydrationWarning
      >
        <I18nProvider>
          <ThemeProvider>
            <MotionRoot>{children}</MotionRoot>
          </ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
