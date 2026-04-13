import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/components/workspace/settings/model-settings-model-refresh.js"),
).href;

async function importHelper() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.didEffectiveModelsChange;
}

void test("effective model changes trigger a model refresh", async () => {
  const didEffectiveModelsChange = await importHelper();

  assert.equal(didEffectiveModelsChange(["gpt-4o"], []), true);
});
