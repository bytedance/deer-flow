import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/core/utils/datetime-normalize.js"),
).href;

async function importNormalizeDateForTimeAgo() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.normalizeDateForTimeAgo;
}

void test("normalizeDateForTimeAgo converts unix-second timestamp strings into Date instances", async () => {
  const normalizeDateForTimeAgo = await importNormalizeDateForTimeAgo();
  const normalized = normalizeDateForTimeAgo("1775877618.3515441");

  assert.ok(normalized instanceof Date);
  assert.equal(normalized.toISOString(), "2026-04-11T03:20:18.351Z");
});
