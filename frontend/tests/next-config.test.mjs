import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const configPath = pathToFileURL(
  path.resolve("frontend/next.config.js"),
).href;

async function loadConfig(query, env = {}) {
  const previous = new Map();

  for (const [key, value] of Object.entries(env)) {
    previous.set(key, process.env[key]);
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }

  try {
    return await import(`${configPath}?${query}`);
  } finally {
    for (const [key, value] of previous.entries()) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

void test("non-bundled frontend proxies desktop backend routes through Next", async () => {
  const imported = await loadConfig("non-bundled-routes", {
    DEER_FLOW_DESKTOP_BUNDLE: undefined,
    NEXT_PUBLIC_BACKEND_BASE_URL: undefined,
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: undefined,
  });

  const rewrites = await imported.default.rewrites();
  const sources = rewrites.map((entry) => entry.source);

  for (const source of [
    "/api/models",
    "/api/skills",
    "/api/skills/:path*",
    "/api/mcp/:path*",
    "/api/threads/:path*",
  ]) {
    assert.ok(sources.includes(source), `missing rewrite for ${source}`);
  }
});

void test("bundled desktop only rewrites gateway routes and keeps Next local APIs reachable", async () => {
  const imported = await loadConfig("bundled-routes", {
    DEER_FLOW_DESKTOP_BUNDLE: "1",
    NEXT_PUBLIC_BACKEND_BASE_URL: undefined,
    NEXT_PUBLIC_LANGGRAPH_BASE_URL: undefined,
  });

  const rewrites = await imported.default.rewrites();
  const sources = rewrites.map((entry) => entry.source);

  assert.ok(sources.includes("/api/langgraph"));
  assert.ok(sources.includes("/api/langgraph/:path*"));

  for (const source of [
    "/api/models",
    "/api/agents",
    "/api/agents/:path*",
    "/api/mcp",
    "/api/mcp/:path*",
    "/api/skills",
    "/api/skills/:path*",
    "/api/threads/:path*",
  ]) {
    assert.ok(sources.includes(source), `missing bundled rewrite for ${source}`);
  }

  assert.equal(
    sources.includes("/api/:path*"),
    false,
    "bundled desktop should not rewrite every Next API route through gateway",
  );
});
