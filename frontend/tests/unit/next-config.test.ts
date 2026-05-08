import { afterEach, describe, expect, test, vi } from "vitest";

async function loadConfig() {
  vi.resetModules();
  return (await import("../../next.config.js")).default;
}

type Rewrite = {
  source: string;
  destination: string;
};

type RewriteGroups = {
  beforeFiles: Rewrite[];
  fallback: Rewrite[];
};

async function loadRewrites() {
  const config = await loadConfig();
  expect(config.rewrites).toBeDefined();
  const rewrites = (await config.rewrites?.()) as RewriteGroups;
  expect(Array.isArray(rewrites)).toBe(false);
  return rewrites;
}

describe("next config rewrites", () => {
  const originalBackendBaseUrl = process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
  const originalGatewayBaseUrl =
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;

  afterEach(() => {
    if (originalBackendBaseUrl === undefined) {
      delete process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
    } else {
      process.env.NEXT_PUBLIC_BACKEND_BASE_URL = originalBackendBaseUrl;
    }
    if (originalGatewayBaseUrl === undefined) {
      delete process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL;
    } else {
      process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL = originalGatewayBaseUrl;
    }
  });

  test("keeps gateway catch-all as fallback so app routes can win first", async () => {
    delete process.env.NEXT_PUBLIC_BACKEND_BASE_URL;
    process.env.DEER_FLOW_INTERNAL_GATEWAY_BASE_URL =
      "http://gateway.example/base/";

    const rewrites = await loadRewrites();

    expect(rewrites.beforeFiles).toContainEqual({
      source: "/api/agents",
      destination: "http://gateway.example/base/api/agents",
    });
    expect(rewrites.beforeFiles).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "/api/langgraph/:path*" }),
      ]),
    );
    expect(rewrites.fallback).toContainEqual({
      source: "/api/:path*",
      destination: "http://gateway.example/base/api/:path*",
    });
  });

  test("preserves fallback coverage for gateway routes not explicitly listed", async () => {
    delete process.env.NEXT_PUBLIC_BACKEND_BASE_URL;

    const rewrites = await loadRewrites();

    expect(rewrites.fallback).toContainEqual(
      expect.objectContaining({
        source: "/api/:path*",
        destination: "http://127.0.0.1:8001/api/:path*",
      }),
    );
  });
});
