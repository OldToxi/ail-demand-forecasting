import type { NextConfig } from "next";

// The whole app is reached through one origin. /api is proxied to the local Django backend,
// so the frontend and API share the origin (no CORS). Override the API base with NEXT_PUBLIC_API_URL.
const nextConfig: NextConfig = {
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
    ];
  },
};

export default nextConfig;
