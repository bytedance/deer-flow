/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/langgraph/:path*",
        destination: "http://127.0.0.1:2024/:path*",
      },
      {
        source: "/api/models/:path*",
        destination: "http://127.0.0.1:8001/api/models/:path*",
      },
      {
        source: "/api/mcp/:path*",
        destination: "http://127.0.0.1:8001/api/mcp/:path*",
      },
      {
        source: "/api/memory/:path*",
        destination: "http://127.0.0.1:8001/api/memory/:path*",
      },
      {
        source: "/api/skills/:path*",
        destination: "http://127.0.0.1:8001/api/skills/:path*",
      },
      {
        source: "/api/agents/:path*",
        destination: "http://127.0.0.1:8001/api/agents/:path*",
      },
      {
        source: "/api/channels/:path*",
        destination: "http://127.0.0.1:8001/api/channels/:path*",
      },
      {
        source: "/api/threads/:path*",
        destination: "http://127.0.0.1:8001/api/threads/:path*",
      },
    ];
  },
};

export default config;
