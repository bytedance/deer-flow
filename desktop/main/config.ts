import fs from "node:fs/promises";

import type { DesktopPaths } from "./paths.js";

export type DesktopProviderSetting = {
  id: string;
  providerType: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

export type ProviderPreset = {
  label: string;
  apiKeyEnv: string;
  use: string;
  baseUrl: string;
  defaultModel: string;
  apiKeyField?: string;
};

export const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  openai: {
    label: "OpenAI",
    apiKeyEnv: "OPENAI_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "",
    defaultModel: "gpt-4o",
  },
  anthropic: {
    label: "Anthropic",
    apiKeyEnv: "ANTHROPIC_API_KEY",
    use: "langchain_anthropic:ChatAnthropic",
    baseUrl: "",
    defaultModel: "claude-sonnet-4-20250514",
  },
  google: {
    label: "Google Gemini",
    apiKeyEnv: "GEMINI_API_KEY",
    use: "langchain_google_genai:ChatGoogleGenerativeAI",
    baseUrl: "",
    defaultModel: "gemini-2.5-pro",
    apiKeyField: "gemini_api_key",
  },
  deepseek: {
    label: "DeepSeek",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
  },
  volcengine: {
    label: "Volcengine (Doubao)",
    apiKeyEnv: "VOLCENGINE_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-seed-1-8-251228",
  },
  moonshot: {
    label: "Moonshot (Kimi)",
    apiKeyEnv: "MOONSHOT_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://api.moonshot.cn/v1",
    defaultModel: "kimi-k2.5",
  },
  minimax: {
    label: "MiniMax",
    apiKeyEnv: "MINIMAX_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://api.minimax.io/v1",
    defaultModel: "MiniMax-M2.5",
  },
  openrouter: {
    label: "OpenRouter",
    apiKeyEnv: "OPENROUTER_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "",
  },
  novita: {
    label: "Novita AI",
    apiKeyEnv: "NOVITA_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://api.novita.ai/openai",
    defaultModel: "",
  },
  "openai-compatible": {
    label: "OpenAI-Compatible",
    apiKeyEnv: "",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "",
    defaultModel: "",
  },
};

export type DesktopSettings = {
  defaultModel: string | null;
  providers: DesktopProviderSetting[];
};

const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  defaultModel: null,
  providers: [],
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
