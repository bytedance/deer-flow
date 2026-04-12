import assert from "node:assert/strict";
import test from "node:test";

const { getPreloadScriptPath } = await import("../dist/main/window-paths.js");
const { getDesktopPaths } = await import("../dist/main/paths.js");

void test("getPreloadScriptPath resolves to the CommonJS preload entry for packaged builds", () => {
  assert.equal(
    getPreloadScriptPath("/Applications/DeerFlow Desktop.app/Contents/Resources/app.asar/dist/main"),
    "/Applications/DeerFlow Desktop.app/Contents/Resources/app.asar/dist/preload/index.cjs",
  );
});

void test("getDesktopPaths keeps shared desktop config isolated in config.desktop.yaml", () => {
  const paths = getDesktopPaths("/tmp/deerflow-user-data", "/repo");

  assert.equal(paths.repoConfigPath, "/repo/config.yaml");
  assert.equal(paths.repoDesktopConfigPath, "/repo/config.desktop.yaml");
  assert.equal(paths.runtimeConfigPath, "/tmp/deerflow-user-data/runtime/config.yaml");
});
