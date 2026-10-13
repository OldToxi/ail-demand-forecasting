import type { NextConfig } from "next";

// The whole app is reached through one origin. /api is proxied to the Django backend,
// so the frontend and API share the origin (no CORS). The rewrite destination is
// configurable via API_DEST (e.g. "http://api:8000" inside Docker); defaults to localhost.
const nextConfig: NextConfig = {
  output: "standalone",
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination:
          (process.env.API_DEST ?? "http://127.0.0.1:8000") + "/api/:path*",
      },
    ];
  },
};

export default nextConfig;
