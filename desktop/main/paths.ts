import path from "node:path";

export type DesktopPaths = {
  userData: string;
  stateDir: string;
  runtimeDir: string;
  outputsDir: string;
  preferencesPath: string;
  secretsPath: string;
  repoConfigPath: string;
  repoExtensionsConfigPath: string;
  repoSkillsPath: string;
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
    preferencesPath: path.join(stateDir, "preferences.json"),
    secretsPath: path.join(stateDir, "secrets.json"),
    repoConfigPath: path.join(repoRoot, "config.yaml"),
    repoExtensionsConfigPath: path.join(repoRoot, "extensions_config.json"),
    repoSkillsPath: path.join(repoRoot, "skills"),
  };
}
