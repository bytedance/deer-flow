import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

export function getCargoBinCandidates({
  env = process.env,
  platform = process.platform,
} = {}) {
  const homeDir = env.USERPROFILE ?? env.HOME;
  const candidates = [];

  if (env.CARGO_HOME) {
    candidates.push(path.join(env.CARGO_HOME, "bin"));
  }

  if (homeDir) {
    candidates.push(path.join(homeDir, ".cargo", "bin"));
  }

  return [...new Set(candidates.filter(Boolean))];
}

export function buildPathWithCargoCandidates({
  env = process.env,
  platform = process.platform,
  pathDelimiter = path.delimiter,
  hasCargoExecutable = (candidate) =>
    existsSync(path.join(candidate, platform === "win32" ? "cargo.exe" : "cargo")),
} = {}) {
  const currentPath = env.PATH ?? "";
  const pathSegments = currentPath.split(pathDelimiter).filter(Boolean);
  const prependSegments = [];

  for (const candidate of getCargoBinCandidates({ env, platform })) {
    if (!hasCargoExecutable(candidate)) {
      continue;
    }

    if (!pathSegments.includes(candidate)) {
      prependSegments.push(candidate);
    }
  }

  return [...prependSegments, ...pathSegments].join(pathDelimiter);
}

export async function main(argv = process.argv.slice(2)) {
  const tauriEntrypoint = require.resolve("@tauri-apps/cli/tauri.js");
  const child = spawn(process.execPath, [tauriEntrypoint, ...argv], {
    stdio: "inherit",
    env: {
      ...process.env,
      PATH: buildPathWithCargoCandidates(),
    },
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }

    process.exit(code ?? 1);
  });
}

export function isDirectExecution({
  argv1 = process.argv[1],
  moduleUrl = import.meta.url,
} = {}) {
  if (!argv1) {
    return false;
  }

  return path.resolve(argv1) === path.resolve(fileURLToPath(moduleUrl));
}

if (isDirectExecution()) {
  await main();
}
