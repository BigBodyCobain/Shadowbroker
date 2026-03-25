import type { NextConfig } from "next";
import os from "os";

// /api/* requests are proxied to the backend by the catch-all route handler at
// src/app/api/[...path]/route.ts, which reads BACKEND_URL at request time.
// Do NOT add rewrites for /api/* here — next.config is evaluated at build time,
// so any URL baked in here ignores the runtime BACKEND_URL env var.

function getLanOrigins(): string[] {
  if (process.env.HOST !== "0.0.0.0") return [];

  const origins = new Set<string>();

  for (const ifaces of Object.values(os.networkInterfaces())) {
    for (const iface of ifaces ?? []) {
      if (iface.family === "IPv4" && !iface.internal) {
        const subnet = iface.address.split(".").slice(0, 3).join(".");
        origins.add(`${subnet}.*`);
      }
    }
  }

  return [...origins];
}

const lanOrigins = getLanOrigins();

const nextConfig: NextConfig = {
  transpilePackages: ["react-map-gl", "mapbox-gl", "maplibre-gl"],
  output: "standalone",
  ...(lanOrigins.length > 0 && { allowedDevOrigins: lanOrigins }),
};

export default nextConfig;
