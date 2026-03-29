/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  async rewrites() {
    const backendBaseUrl = process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
    const langgraphBaseUrl = process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;

    if (backendBaseUrl || langgraphBaseUrl) {
      return [];
    }

    return [
      {
        source: "/api/langgraph/:path*",
        destination: "http://127.0.0.1:2024/:path*",
      },
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8001/api/:path*",
      },
    ];
  },
};

export default config;
