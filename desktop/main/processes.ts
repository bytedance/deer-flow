import { spawn, type ChildProcess } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";

import type { DesktopPaths } from "./paths.js";
import { PROVIDER_PRESETS } from "./config.js";
import {
  getBundledFrontendURL,
  getBundledRuntimeEnv,
  getBundledRuntimePorts,
} from "./runtime-ports.js";
import { waitForModelsApiReady } from "./runtime-readiness.js";
import { getSecret } from "./secrets.js";
import { buildRuntimeConfigContent } from "./runtime-config.js";
import type { DesktopSettings } from "./config.js";

export type RuntimeMode = "shared" | "bundled";

export type RuntimeProcessController = {
  start: () => Promise<void>;
  stop: () => Promise<void>;
  restart: () => Promise<void>;
  syncConfig: () => Promise<void>;
  waitUntilReady: () => Promise<void>;
  getURL: () => string;
};

export function getDesktopRepoConfigPath(paths: DesktopPaths, mode: RuntimeMode) {
  return mode === "shared" ? paths.repoDesktopConfigPath : paths.repoConfigPath;
}

function waitForPort(port: number, host: string, timeoutMs: number) {
  return new Promise<void>((resolve, reject) => {
    const startedAt = Date.now();

    const tryConnect = () => {
      const socket = net.createConnection({ port, host });

      socket.once("connect", () => {
        socket.end();
        resolve();
      });

      socket.once("error", () => {
        socket.destroy();
        if (Date.now() - startedAt >= timeoutMs) {
          reject(new Error(`Timed out waiting for ${host}:${port}`));
          return;
        }
        setTimeout(tryConnect, 500);
      });
    };

    tryConnect();
  });
}

function getBackendPythonPath(venvRoot: string) {
  if (process.platform === "win32") {
    return path.join(venvRoot, "Scripts", "python.exe");
  }
  return path.join(venvRoot, "bin", "python");
}

async function getNodeRunnerBinary(paths: DesktopPaths) {
  try {
    await fs.access(paths.bundledNodeBinaryPath);
    return paths.bundledNodeBinaryPath;
  } catch {
    return process.execPath;
  }
}

async function createLogFiles(runtimeDir: string, name: string) {
  const logsDir = path.join(runtimeDir, "logs");
  await fs.mkdir(logsDir, { recursive: true });
  return {
    stdout: openSync(path.join(logsDir, `${name}.log`), "a"),
    stderr: openSync(path.join(logsDir, `${name}.err.log`), "a"),
  };
}

export function createRuntimeProcessController(options: {
  paths: DesktopPaths;
  getSettings: () => Promise<DesktopSettings>;
  mode: RuntimeMode;
}): RuntimeProcessController {
  let gatewayProcess: ChildProcess | null = null;
  let frontendProcess: ChildProcess | null = null;

  const bundledPorts = getBundledRuntimePorts();
  const frontendURL = options.mode === "bundled"
    ? getBundledFrontendURL()
    : "http://127.0.0.1:2026";

  async function readSettingsAndSecrets() {
    const settings = await options.getSettings();
    const providerSecrets = Object.fromEntries(
      await Promise.all(
        settings.providers.map(async (provider) => [
          provider.apiKeyEnv,
          (await getSecret(provider.apiKeyEnv)) ?? undefined,
        ] as const),
      ),
    );

    return { settings, providerSecrets };
  }

  async function readConfigTemplate() {
    try {
      return await fs.readFile(getDesktopRepoConfigPath(options.paths, options.mode), "utf8");
    } catch {
      return await fs.readFile(options.paths.repoConfigExamplePath, "utf8");
    }
  }

  async function syncSharedConfig() {
    const configTemplate = await readConfigTemplate();
    const { settings, providerSecrets } = await readSettingsAndSecrets();
    const nextConfigContent = buildRuntimeConfigContent(
      configTemplate,
      settings.providers,
      PROVIDER_PRESETS,
      providerSecrets,
    );

    await fs.writeFile(options.paths.runtimeConfigPath, nextConfigContent, "utf8");

    if (options.mode === "shared") {
      await fs.writeFile(options.paths.repoDesktopConfigPath, nextConfigContent, "utf8");
    }
  }

  async function startBundledGateway() {
    if (gatewayProcess !== null) {
      return;
    }

    const pythonBin = getBackendPythonPath(options.paths.bundledBackendVenvPath);
    const logs = await createLogFiles(options.paths.runtimeDir, "gateway");
    const env = {
      ...process.env,
      PYTHONPATH: options.paths.bundledBackendRootPath,
      DEER_DESKTOP: "1",
      DEER_FLOW_CONFIG_PATH: options.paths.runtimeConfigPath,
      DEER_FLOW_EXTENSIONS_CONFIG_PATH: options.paths.repoExtensionsConfigPath,
      DEER_FLOW_HOME: options.paths.runtimeDir,
    };

    gatewayProcess = spawn(
      pythonBin,
      [
        "-m",
        "uvicorn",
        "app.gateway.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(bundledPorts.gatewayPort),
      ],
      {
        cwd: options.paths.bundledBackendRootPath,
        env,
        stdio: ["ignore", logs.stdout, logs.stderr],
      },
    );

    gatewayProcess.once("exit", () => {
      closeSync(logs.stdout);
      closeSync(logs.stderr);
      gatewayProcess = null;
    });
  }

  async function startBundledFrontend() {
    if (frontendProcess !== null) {
      return;
    }

    const logs = await createLogFiles(options.paths.runtimeDir, "frontend");
    const env = {
      ...process.env,
      ...getBundledRuntimeEnv(),
    };

    frontendProcess = spawn(
      await getNodeRunnerBinary(options.paths),
      [options.paths.bundledFrontendServerPath],
      {
        cwd: options.paths.bundledFrontendRootPath,
        env,
        stdio: ["ignore", logs.stdout, logs.stderr],
      },
    );

    frontendProcess.once("exit", () => {
      closeSync(logs.stdout);
      closeSync(logs.stderr);
      frontendProcess = null;
    });
  }

  async function start() {
    const settings = await options.getSettings();
    if (options.mode === "bundled" || settings.providers.length > 0) {
      await syncSharedConfig();
    }

    if (options.mode === "shared") {
      return;
    }

    await startBundledGateway();
    await waitForPort(bundledPorts.gatewayPort, "127.0.0.1", 120_000);
    await startBundledFrontend();
  }

  async function stop() {
    const children = [frontendProcess, gatewayProcess].filter(
      (child): child is ChildProcess => child !== null,
    );

    frontendProcess = null;
    gatewayProcess = null;

    await Promise.all(
      children.map(
        (child) =>
          new Promise<void>((resolve) => {
            child.once("exit", () => resolve());
            child.kill("SIGTERM");
            setTimeout(() => {
              child.kill("SIGKILL");
              resolve();
            }, 10_000);
          }),
      ),
    );
  }

  return {
    start,
    stop,
    restart: async () => {
      await stop();
      await start();
    },
    syncConfig: async () => {
      await syncSharedConfig();
    },
    waitUntilReady: async () => {
      await waitForPort(options.mode === "bundled" ? 3000 : 2026, "127.0.0.1", 120_000);
      await waitForModelsApiReady(`${frontendURL}/api/models`);
    },
    getURL: () => frontendURL,
  };
}
