import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/core/config/server-backend-base-url.js"),
).href;

async function resolveBackendBaseURL(query, env = {}) {
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
    return imported.getServerBackendBaseURL();
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

void test("server backend URL uses NEXT_PUBLIC_BACKEND_BASE_URL when it is set", async () => {
  const backendBaseURL = await resolveBackendBaseURL("explicit-backend", {
    NEXT_PUBLIC_BACKEND_BASE_URL: "http://127.0.0.1:9000/",
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:8002",
  });

  assert.equal(backendBaseURL, "http://127.0.0.1:9000");
});

void test("server backend URL falls back to the bundled internal gateway when NEXT_PUBLIC_BACKEND_BASE_URL is empty", async () => {
  const backendBaseURL = await resolveBackendBaseURL("bundled-fallback", {
    NEXT_PUBLIC_BACKEND_BASE_URL: "",
    DEER_FLOW_INTERNAL_GATEWAY_BASE_URL: "http://127.0.0.1:8002/",
  });

  assert.equal(backendBaseURL, "http://127.0.0.1:8002");
});
