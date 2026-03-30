import assert from "node:assert/strict";
import process from "node:process";

process.env.SKIP_ENV_VALIDATION = "1";
process.env.NODE_ENV = "development";

const configModule = await import("../next.config.js");
const config = configModule?.default ?? configModule;

assert.equal(typeof config.rewrites, "function", "next.config.js must export rewrites() in dev");

const rewrites = await config.rewrites();
assert.ok(rewrites && typeof rewrites === "object", "rewrites() must return an object");
assert.ok(Array.isArray(rewrites.fallback), "rewrites() must return { fallback: [...] }");

const fallback = rewrites.fallback;

for (const rule of fallback) {
  assert.ok(
    typeof rule?.source === "string",
    "each fallback rewrite must have a string 'source'"
  );
  assert.ok(
    !rule.source.startsWith("/api/auth"),
    "must not add rewrites for /api/auth/*"
  );
}

assert.ok(
  fallback.some(
    (r) =>
      r.source === "/api/langgraph/:path*" &&
      r.destination === "http://localhost:2024/:path*"
  ),
  "must rewrite /api/langgraph/:path* to http://localhost:2024/:path*"
);

assert.ok(
  fallback.some(
    (r) =>
      r.source === "/api/:path*" &&
      r.destination === "http://localhost:8001/api/:path*"
  ),
  "must rewrite /api/:path* to http://localhost:8001/api/:path*"
);
