import assert from "node:assert/strict";
import test from "node:test";

const { buildBackendUrl } = await import(new URL("./_proxy.ts", import.meta.url).href);

void test("preserves query strings when proxying to the backend", () => {
  const url = buildBackendUrl(
    "/api/memory/facts",
    "http://localhost:3000/api/memory/facts?limit=1&cursor=next-page",
    "http://127.0.0.1:8001",
  );

  assert.equal(url.toString(), "http://127.0.0.1:8001/api/memory/facts?limit=1&cursor=next-page");
});

void test("leaves query string empty when the incoming request has none", () => {
  const url = buildBackendUrl(
    "/api/memory",
    "http://localhost:3000/api/memory",
    "http://127.0.0.1:8001",
  );

  assert.equal(url.toString(), "http://127.0.0.1:8001/api/memory");
});
