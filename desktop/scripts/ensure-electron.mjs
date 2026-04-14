import { spawnSync } from "node:child_process";
import { constants as fsConstants } from "node:fs";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function getDefaultPlatformBinaryPath(platform = process.platform) {
  switch (platform) {
    case "darwin":
    case "mas":
      return "Electron.app/Contents/MacOS/Electron";
    case "linux":
    case "freebsd":
    case "openbsd":
      return "electron";
    case "win32":
      return "electron.exe";
    default:
      throw new Error(`Unsupported Electron platform: ${platform}`);
  }
}

async function exists(targetPath) {
  try {
    await access(targetPath, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

export async function getElectronInstallStatus({
  desktopDir = path.resolve(__dirname, ".."),
  platform = process.platform,
} = {}) {
  const electronDir = path.join(desktopDir, "node_modules", "electron");
  const distDir = path.join(electronDir, "dist");
  const versionFile = path.join(distDir, "version");
  const pathFile = path.join(electronDir, "path.txt");
  const defaultBinaryPath = getDefaultPlatformBinaryPath(platform);

  if (!(await exists(electronDir))) {
    return {
      needsInstall: true,
      reason: "package-missing",
      expectedBinaryPath: path.join(distDir, defaultBinaryPath),
    };
  }

  if (!(await exists(versionFile))) {
    return {
      needsInstall: true,
      reason: "version-missing",
      expectedBinaryPath: path.join(distDir, defaultBinaryPath),
    };
  }

  let relativeBinaryPath = defaultBinaryPath;
  if (await exists(pathFile)) {
    relativeBinaryPath = (await readFile(pathFile, "utf8")).trim() || defaultBinaryPath;
  }

  const expectedBinaryPath = path.join(distDir, relativeBinaryPath);
  if (!(await exists(expectedBinaryPath))) {
    return {
      needsInstall: true,
      reason: "binary-missing",
      expectedBinaryPath,
    };
  }

  return {
    needsInstall: false,
    reason: null,
    expectedBinaryPath,
  };
}

function formatReason(reason) {
  switch (reason) {
    case "package-missing":
      return "desktop dependencies are not installed";
    case "version-missing":
      return "Electron package metadata is incomplete";
    case "binary-missing":
      return "Electron binary is missing from node_modules";
    default:
      return "Electron installation is incomplete";
  }
}

export function getElectronRepairCommand({ reason }) {
  if (reason === "version-missing" || reason === "binary-missing") {
    return {
      cmd: process.execPath,
      args: ["node_modules/electron/install.js"],
    };
  }

  return {
    cmd: "pnpm",
    args: ["install"],
  };
}

export async function ensureElectronInstall({
  desktopDir = path.resolve(__dirname, ".."),
} = {}) {
  const status = await getElectronInstallStatus({ desktopDir });
  if (!status.needsInstall) {
    return status;
  }

  console.warn(`[desktop] ${formatReason(status.reason)}; repairing in ${desktopDir}`);

  const repairCommand = getElectronRepairCommand({ reason: status.reason });
  console.warn(
    `[desktop] attempting repair with: ${repairCommand.cmd} ${repairCommand.args.join(" ")}`,
  );

  const installResult = spawnSync(repairCommand.cmd, repairCommand.args, {
    cwd: desktopDir,
    stdio: "inherit",
    env: process.env,
  });

  if (installResult.status !== 0) {
    throw new Error(
      `desktop dependency repair failed with exit code ${installResult.status ?? "unknown"}`,
    );
  }

  const rechecked = await getElectronInstallStatus({ desktopDir });
  if (rechecked.needsInstall) {
    throw new Error(
      `[desktop] Electron is still unavailable after pnpm install (${rechecked.reason} at ${rechecked.expectedBinaryPath})`,
    );
  }

  return rechecked;
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  ensureElectronInstall().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
