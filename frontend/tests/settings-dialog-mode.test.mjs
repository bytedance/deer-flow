import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const helperPath = pathToFileURL(
  path.resolve("frontend/src/components/workspace/settings/settings-dialog-mode.js"),
).href;

async function importHelper() {
  const imported = await import(`${helperPath}?test=${Date.now()}`);
  return imported.shouldShowDesktopModelSettings;
}

void test("shared desktop mode does not show desktop model settings", async () => {
  const shouldShowDesktopModelSettings = await importHelper();

  assert.equal(
    shouldShowDesktopModelSettings({
      hasDesktopBridge: true,
      runtimeMode: "shared",
    }),
    false,
  );
});
