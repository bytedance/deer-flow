import fs from "node:fs/promises";

import type { DesktopPaths } from "./paths.js";

export type DesktopProviderSetting = {
  id: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
};

export type DesktopSettings = {
  defaultModel: string | null;
  providers: DesktopProviderSetting[];
};

const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  defaultModel: null,
  providers: [
    {
      id: "openai",
      label: "OpenAI",
      apiKeyEnv: "OPENAI_API_KEY",
      baseUrl: "",
    },
    {
      id: "anthropic",
      label: "Anthropic",
      apiKeyEnv: "ANTHROPIC_API_KEY",
      baseUrl: "",
    },
    {
      id: "deepseek",
      label: "DeepSeek",
      apiKeyEnv: "DEEPSEEK_API_KEY",
      baseUrl: "",
    },
  ],
};

export async function ensureDesktopDirectories(paths: DesktopPaths) {
  await Promise.all([
    fs.mkdir(paths.userData, { recursive: true }),
    fs.mkdir(paths.stateDir, { recursive: true }),
    fs.mkdir(paths.runtimeDir, { recursive: true }),
    fs.mkdir(paths.outputsDir, { recursive: true }),
  ]);
}

export async function readDesktopSettings(paths: DesktopPaths): Promise<DesktopSettings> {
  try {
    const raw = await fs.readFile(paths.preferencesPath, "utf8");
    const parsed = JSON.parse(raw) as Partial<DesktopSettings>;
    return {
      ...DEFAULT_DESKTOP_SETTINGS,
      ...parsed,
      providers: parsed.providers ?? DEFAULT_DESKTOP_SETTINGS.providers,
    };
  } catch {
    return DEFAULT_DESKTOP_SETTINGS;
  }
}

export async function writeDesktopSettings(paths: DesktopPaths, settings: DesktopSettings) {
  await fs.writeFile(paths.preferencesPath, JSON.stringify(settings, null, 2), "utf8");
}

export async function ensureDesktopConfigFiles(paths: DesktopPaths, settings: DesktopSettings) {
  await fs.access(paths.repoConfigPath);
  await fs.access(paths.repoExtensionsConfigPath);
  await fs.access(paths.repoSkillsPath);
  await writeDesktopSettings(paths, settings);
}
