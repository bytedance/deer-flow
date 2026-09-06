#!/usr/bin/env node

import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * @param {string} _platform
 * @param {Record<string, string | undefined>} env
 */
export function getDevBundler(_platform = process.platform, env = process.env) {
  const override = env.DEER_FLOW_DEV_BUNDLER?.trim();
  if (override) {
    if (override !== "turbo" && override !== "webpack") {
      throw new Error(
        'DEER_FLOW_DEV_BUNDLER must be either "turbo" or "webpack"',
      );
    }
    return override;
  }
  // Keep Webpack as the cross-platform default while #5132's Turbopack
  // PostCSS worker leak remains unfixed in a stable Next.js release. Retain
  // the platform parameter so restoring the platform-aware default stays a
  // small change once the upstream fix is stable and verified on macOS/Linux.
  return "webpack";
}

/**
 * @param {string} platform
 * @param {string[]} extraArgs
 * @param {Record<string, string | undefined>} env
 */
export function getNextDevArgs(
  platform = process.platform,
  extraArgs = [],
  env = process.env,
) {
  const nextArgs = extraArgs[0] === "--" ? extraArgs.slice(1) : extraArgs;
  return ["dev", `--${getDevBundler(platform, env)}`, ...nextArgs];
}

function startDevServer() {
  const frontendDir = fileURLToPath(new URL("..", import.meta.url));
  const nextBin = fileURLToPath(
    new URL("../node_modules/next/dist/bin/next", import.meta.url),
  );
  const child = spawn(
    process.execPath,
    [nextBin, ...getNextDevArgs(process.platform, process.argv.slice(2))],
    {
      cwd: frontendDir,
      env: process.env,
      stdio: "inherit",
    },
  );

  child.on("error", (error) => {
    console.error(`Failed to start Next.js: ${error.message}`);
    process.exitCode = 1;
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exitCode = code ?? 1;
  });
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  startDevServer();
}
