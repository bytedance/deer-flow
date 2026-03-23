/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return {
        fallback: [],
      };
    }

    return {
      fallback: [
        {
          source: "/api/langgraph/:path*",
          destination: "http://localhost:2024/:path*",
        },
        {
          source: "/api/:path*",
          destination: "http://localhost:8001/api/:path*",
        },
      ],
    };
  },
};

export default config;
