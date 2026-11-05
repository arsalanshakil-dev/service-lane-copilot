import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The app is often opened through the 127.0.0.1 loopback alias in Windows.
  // Allow Next's development assets and HMR from that host as well as localhost.
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/copilot/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
