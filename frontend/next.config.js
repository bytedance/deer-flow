/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";
import {
  hasConfiguredEnvValue,
  resolveInternalGatewayUrl,
} from "./src/core/gateway-url.js";

import nextra from "nextra";

const withNextra = nextra({});

/** @type {import("next").NextConfig} */
const config = {
  output:
    process.env.NEXT_CONFIG_BUILD_OUTPUT === "standalone"
      ? "standalone"
      : undefined,
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  async rewrites() {
    const beforeFiles = [];
    const fallback = [];
    const gatewayURL = resolveInternalGatewayUrl();

    if (!hasConfiguredEnvValue(process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL)) {
      fallback.push({
        source: "/api/langgraph",
        destination: `${gatewayURL}/api`,
      });
      fallback.push({
        source: "/api/langgraph/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    if (!hasConfiguredEnvValue(process.env.NEXT_PUBLIC_BACKEND_BASE_URL)) {
      beforeFiles.push({
        source: "/api/agents",
        destination: `${gatewayURL}/api/agents`,
      });
      beforeFiles.push({
        source: "/api/agents/:path*",
        destination: `${gatewayURL}/api/agents/:path*`,
      });
      beforeFiles.push({
        source: "/api/skills",
        destination: `${gatewayURL}/api/skills`,
      });
      beforeFiles.push({
        source: "/api/skills/:path*",
        destination: `${gatewayURL}/api/skills/:path*`,
      });

      fallback.push({
        source: "/api/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    return {
      beforeFiles,
      afterFiles: [],
      fallback,
    };
  },
};

export default withNextra(config);
