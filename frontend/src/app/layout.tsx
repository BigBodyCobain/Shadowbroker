import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/lib/ThemeContext";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {,
  title: "WORLDVIEW // ORBITAL TRACKING",
  description: "Advanced Geopolitical Risk Dashboard"
  manifest: "/manifest.json",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head />
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-[var(--bg-primary)]`}
        suppressHydrationWarning
      >
        <ThemeProvider>{children}</ThemeProvider>
            <script dangerouslySetInnerHTML={{__html: `if ('serviceWorker' in navigator) { navigator.serviceWorker.register('/sw.js'); }`}} />
      </body>
    </html>
  );
}
