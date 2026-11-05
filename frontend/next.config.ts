import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // The app is often opened through the 127.0.0.1 loopback alias in Windows.
  // Allow Next's development assets and HMR from that host as well as localhost.
  allowedDevOrigins: ["127.0.0.1"],
  experimental: {
    // The /api/copilot rewrite proxy hangs up after 30 s by default. Local Ollama chat,
    // AI drafts, and AI suggestions routinely take longer on CPU-only machines, so allow
    // up to the backend's maximum per-request Ollama timeout (OLLAMA_TIMEOUT_SECONDS ≤ 1800).
    proxyTimeout: 1_800_000,
  },
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
