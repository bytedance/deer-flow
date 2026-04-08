import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs/promises";
import net from "node:net";
import path from "node:path";

import type { DesktopPaths } from "./paths.js";
import { readDesktopSettings, PROVIDER_PRESETS, type DesktopProviderSetting } from "./config.js";
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

  function generateModelEntry(provider: DesktopProviderSetting) {
    const preset = PROVIDER_PRESETS[provider.providerType];
    const use = preset?.use ?? "langchain_openai:ChatOpenAI";
    const apiKeyField = preset?.apiKeyField ?? "api_key";

    const entry: Record<string, unknown> = {
      name: provider.defaultModel || provider.id,
      display_name: `${provider.label} - ${provider.defaultModel || "default"}`,
      use,
      model: provider.defaultModel,
      [apiKeyField]: `$${provider.apiKeyEnv}`,
      request_timeout: 600.0,
      max_retries: 2,
    };

    if (provider.baseUrl) {
      const baseUrlField = use.includes("patched_deepseek") ? "api_base" : "base_url";
      entry[baseUrlField] = provider.baseUrl;
    }

    return entry;
  }

  async function generateRuntimeConfig(
    repoConfigPath: string,
    runtimeConfigPath: string,
    providers: DesktopProviderSetting[],
  ) {
    let configContent = await fs.readFile(repoConfigPath, "utf8");

    const modelEntries = providers
      .filter((p) => p.defaultModel)
      .map(generateModelEntry);

    const modelsYaml =
      modelEntries.length === 0
        ? "models: []"
        : "models:\n" +
          modelEntries
            .map((entry) => {
              const lines = Object.entries(entry)
                .map(([key, value]) => {
                  if (typeof value === "string")
                    return `    ${key}: ${value.startsWith("$") ? value : JSON.stringify(value)}`;
                  return `    ${key}: ${value}`;
                })
                .join("\n");
              return `  - ${lines.trimStart().replace(/^    /, "")}`;
            })
            .join("\n");

    configContent = configContent.replace(
      /^models:\s*\[\].*?(?=\n\S|\n#\s*=)/ms,
      modelsYaml + "\n",
    );

    await fs.writeFile(runtimeConfigPath, configContent, "utf8");
  }

  async function start() {
    if (runtimeProcess !== null) {
      return;
    }

    const settings = await readDesktopSettings(options.paths);
    const runtimeConfigPath = options.paths.runtimeConfigPath;
    await generateRuntimeConfig(
      options.paths.repoConfigPath,
      runtimeConfigPath,
      settings.providers,
    );
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
      DEER_FLOW_CONFIG_PATH: runtimeConfigPath,
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
