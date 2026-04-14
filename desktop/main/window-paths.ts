import path from "node:path";

export function getPreloadScriptPath(mainDir: string) {
  return path.join(mainDir, "../preload/index.cjs");
}
