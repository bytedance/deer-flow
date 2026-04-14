/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
import nextra from "nextra";

const withNextra = nextra({});
const isDesktopBundle = process.env.DEER_FLOW_DESKTOP_BUNDLE === "1";

function appendGatewayRewriteTargets(rewrites, gatewayURL) {
  for (const route of [
    "/api/models",
    "/api/agents",
    "/api/agents/:path*",
    "/api/mcp",
    "/api/mcp/:path*",
    "/api/skills",
    "/api/skills/:path*",
    "/api/threads/:path*",
  ]) {
    rewrites.push({
      source: route,
      destination: `${gatewayURL}${route}`,
    });
  }
}

/** @type {import("next").NextConfig} */
const config = {
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  ...(isDesktopBundle ? { output: "standalone" } : {}),
  async rewrites() {
    const rewrites = [];
    const langgraphURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL",
      "http://127.0.0.1:2024",
    );
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8001",
    );

    if (isDesktopBundle) {
      rewrites.push({
        source: "/api/langgraph",
        destination: `${gatewayURL}/api`,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
      appendGatewayRewriteTargets(rewrites, gatewayURL);
      return rewrites;
    }

    if (!process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
      rewrites.push({
        source: "/api/langgraph",
        destination: langgraphURL,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${langgraphURL}/:path*`,
      });
    }

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      appendGatewayRewriteTargets(rewrites, gatewayURL);
    }

    return rewrites;
  },
};

export default withNextra(config);
