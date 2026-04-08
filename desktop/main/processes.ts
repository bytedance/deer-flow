import { spawn, type ChildProcess } from "node:child_process";
import net from "node:net";
import path from "node:path";

import type { DesktopPaths } from "./paths.js";
import { readDesktopSettings } from "./config.js";
import { getSecret } from "./secrets.js";

export type RuntimeProcessController = {
  start: () => Promise<void>;
  stop: () => Promise<void>;
  restart: () => Promise<void>;
  waitUntilReady: () => Promise<void>;
  getURL: () => string;
};

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

export function createRuntimeProcessController(options: {
  repoRoot: string;
  paths: DesktopPaths;
}): RuntimeProcessController {
  let runtimeProcess: ChildProcess | null = null;

  const frontendURL = "http://127.0.0.1:2026";

  async function start() {
    if (runtimeProcess !== null) {
      return;
    }

    const settings = await readDesktopSettings(options.paths);
    const providerSecrets = Object.fromEntries(
      await Promise.all(
        settings.providers.map(async (provider) => [provider.apiKeyEnv, (await getSecret(provider.apiKeyEnv)) ?? undefined] as const),
      ),
    );

    const providerBaseUrls = Object.fromEntries(
      settings.providers
        .filter((provider) => provider.baseUrl.trim())
        .map((provider) => [`DEER_DESKTOP_PROVIDER_BASE_URL_${provider.id.toUpperCase()}`, provider.baseUrl.trim()] as const),
    );

    const env = {
      ...process.env,
      DEER_DESKTOP: "1",
      DEER_FLOW_CONFIG_PATH: options.paths.repoConfigPath,
      DEER_FLOW_EXTENSIONS_CONFIG_PATH: options.paths.repoExtensionsConfigPath,
      DEER_FLOW_HOME: options.paths.runtimeDir,
      ...providerSecrets,
      ...providerBaseUrls,
    };

    const child = spawn(
      "bash",
      [path.join(options.repoRoot, "scripts/serve.sh"), "--restart", "--dev", "--gateway", "--skip-install"],
      {
        cwd: options.repoRoot,
        env,
        stdio: "pipe",
      },
    );

    runtimeProcess = child;

    child.once("exit", () => {
      runtimeProcess = null;
    });
  }

  async function stop() {
    if (runtimeProcess === null) {
      return;
    }

    const child = runtimeProcess;
    runtimeProcess = null;

    await new Promise<void>((resolve) => {
      child.once("exit", () => resolve());
      child.kill("SIGTERM");
      setTimeout(() => {
        child.kill("SIGKILL");
        resolve();
      }, 10_000);
    });
  }

  return {
    start,
    stop,
    restart: async () => {
      await stop();
      await start();
    },
    waitUntilReady: async () => {
      await waitForPort(2026, "127.0.0.1", 120_000);
    },
    getURL: () => frontendURL,
  };
}
