/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  async rewrites() {
    if (process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      return [];
    }

    return [
      {
        source: "/api/agents/:path*",
        destination: "http://127.0.0.1:8001/api/agents/:path*",
      },
    ];
  },
};

export default config;
