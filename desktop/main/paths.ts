import path from "node:path";

export type DesktopPaths = {
  userData: string;
  stateDir: string;
  runtimeDir: string;
  outputsDir: string;
  bundleDir: string;
  preferencesPath: string;
  secretsPath: string;
  repoConfigPath: string;
  repoDesktopConfigPath: string;
  repoConfigExamplePath: string;
  repoExtensionsConfigPath: string;
  repoExtensionsConfigExamplePath: string;
  repoSkillsPath: string;
  bundledBackendRootPath: string;
  bundledBackendVenvPath: string;
  bundledFrontendRootPath: string;
  bundledFrontendServerPath: string;
  bundledNodeBinaryPath: string;
  runtimeConfigPath: string;
};

export function getDesktopPaths(userData: string, repoRoot: string): DesktopPaths {
  const stateDir = path.join(userData, "state");
  const runtimeDir = path.join(userData, "runtime");
  const outputsDir = path.join(userData, "outputs");

  return {
    userData,
    stateDir,
    runtimeDir,
    outputsDir,
    bundleDir: path.join(repoRoot, "bundle-resources", "app-bundle"),
    preferencesPath: path.join(stateDir, "preferences.json"),
    secretsPath: path.join(stateDir, "secrets.json"),
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
    bundledNodeBinaryPath: path.join(
      repoRoot,
      "node-runtime",
      process.platform === "win32" ? "node.exe" : "node",
    ),
    runtimeConfigPath: path.join(runtimeDir, "config.yaml"),
  };
}
