/** @type {import('next').NextConfig} */
const nextConfig = {
  // Chat requests that trigger MCP tool calls (DB queries + Gemini round
  // trips) can take well over Next's 30s default rewrite-proxy timeout,
  // which otherwise kills the connection mid-response ("socket hang up").
  experimental: {
    proxyTimeout: 120_000,
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
