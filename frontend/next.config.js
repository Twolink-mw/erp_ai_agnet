/** @type {import('next').NextConfig} */
const nextConfig = {
  // Chat requests that trigger MCP tool calls (DB queries + Gemini round
  // trips) can take well over Next's 30s default rewrite-proxy timeout,
  // which otherwise kills the connection mid-response ("socket hang up").
  // Multi-step analytical questions (e.g. month-over-month rank comparisons)
  // can burn many tool rounds plus occasional slow Gemini API responses
  // (observed 100s+ single-call latency spikes), so 120s was still not
  // enough in practice — bumped to 240s to give real headroom.
  experimental: {
    proxyTimeout: 240_000,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.BACKEND_URL || "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
