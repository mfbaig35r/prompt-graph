import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 treats 127.0.0.1 as a cross-origin host and blocks /_next dev resources from it,
  // which silently prevents hydration (the page renders its server HTML and never fetches).
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // The floating dev badge overlays the page and has no place in a demo.
  devIndicators: false,
};

export default nextConfig;
