import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/core/config/server-base-origin.js"),
).href;

async function resolveOrigin(query, env = {}) {
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
    const imported = await import(`${helperPath}?${query}-${Date.now()}`);
    return imported.getServerBaseOrigin();
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

void test("desktop SSR uses BETTER_AUTH_BASE_URL as the absolute frontend origin", async () => {
  const origin = await resolveOrigin("desktop-ssr", {
    BETTER_AUTH_BASE_URL: "http://127.0.0.1:3000",
    HOSTNAME: "127.0.0.1",
    PORT: "3000",
  });

  assert.equal(origin, "http://127.0.0.1:3000");
});

void test("server falls back to hostname and port when BETTER_AUTH_BASE_URL is missing", async () => {
  const origin = await resolveOrigin("hostname-port", {
    BETTER_AUTH_BASE_URL: undefined,
    HOSTNAME: "127.0.0.1",
    PORT: "3000",
  });

  assert.equal(origin, "http://127.0.0.1:3000");
});

void test("server uses nginx default when no desktop runtime origin is available", async () => {
  const origin = await resolveOrigin("default-origin", {
    BETTER_AUTH_BASE_URL: undefined,
    HOSTNAME: undefined,
    PORT: undefined,
  });

  assert.equal(origin, "http://localhost:2026");
});
