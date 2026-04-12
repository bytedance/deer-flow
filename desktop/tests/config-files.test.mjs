import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const { ensureDesktopConfigFiles } = await import("../dist/main/config.js");

async function createPaths() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "deer-desktop-config-"));
  const userData = path.join(root, "user-data");
  const repoRoot = path.join(root, "repo");

  await fs.mkdir(userData, { recursive: true });
  await fs.mkdir(path.join(userData, "state"), { recursive: true });
  await fs.mkdir(path.join(userData, "runtime"), { recursive: true });
  await fs.mkdir(path.join(userData, "outputs"), { recursive: true });
  await fs.mkdir(path.join(repoRoot, "skills"), { recursive: true });
  await fs.writeFile(path.join(repoRoot, "config.yaml"), "models: []\n", "utf8");
  await fs.writeFile(path.join(repoRoot, "config.example.yaml"), "models: []\n", "utf8");
  await fs.writeFile(path.join(repoRoot, "extensions_config.json"), "{}\n", "utf8");

  return {
    userData,
    stateDir: path.join(userData, "state"),
    runtimeDir: path.join(userData, "runtime"),
    outputsDir: path.join(userData, "outputs"),
    bundleDir: path.join(repoRoot, "bundle-resources", "app-bundle"),
    preferencesPath: path.join(userData, "state", "preferences.json"),
    secretsPath: path.join(userData, "state", "secrets.json"),
    repoConfigPath: path.join(repoRoot, "config.yaml"),
    repoDesktopConfigPath: path.join(repoRoot, "config.desktop.yaml"),
    repoConfigExamplePath: path.join(repoRoot, "config.example.yaml"),
    repoExtensionsConfigPath: path.join(repoRoot, "extensions_config.json"),
    repoExtensionsConfigExamplePath: path.join(repoRoot, "extensions_config.example.json"),
    repoSkillsPath: path.join(repoRoot, "skills"),
    bundledBackendRootPath: path.join(repoRoot, "backend"),
    bundledBackendVenvPath: path.join(repoRoot, "backend", ".venv"),
    bundledFrontendRootPath: repoRoot,
    bundledFrontendServerPath: path.join(repoRoot, "server.js"),
    bundledNodeBinaryPath: path.join(repoRoot, "node-runtime", "node"),
    runtimeConfigPath: path.join(userData, "runtime", "config.yaml"),
  };
}

void test("shared mode seeds config.desktop.yaml from the repo config", async () => {
  const paths = await createPaths();

  await ensureDesktopConfigFiles(paths, { defaultModel: null, providers: [] }, "shared");

  const content = await fs.readFile(paths.repoDesktopConfigPath, "utf8");
  assert.equal(content, "models: []\n");
});

void test("bundled mode does not create repo config.desktop.yaml inside the bundle", async () => {
  const paths = await createPaths();

  await ensureDesktopConfigFiles(paths, { defaultModel: null, providers: [] }, "bundled");

  const repoFiles = await fs.readdir(path.dirname(paths.repoDesktopConfigPath));
  assert.equal(repoFiles.includes(path.basename(paths.repoDesktopConfigPath)), false);
});
