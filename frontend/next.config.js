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
        source: '/api/langgraph/:path*',
        destination: `${process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL}/:path*`,
      },
    ]
  }
};

export default config;
