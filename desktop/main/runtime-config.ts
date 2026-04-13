import type { DesktopProviderSetting, ProviderPreset } from "./config.js";

type ProviderSecretMap = Record<string, string | undefined>;
type DesktopProviderWithSecret = DesktopProviderSetting & {
  secret?: string | undefined;
};

const TOP_LEVEL_KEY_PATTERN = /^[A-Za-z0-9_-]+:\s*(?:#.*)?$/;

function quoteYamlString(value: string) {
  return JSON.stringify(value);
}

function serializeModelEntryYaml(entry: Record<string, unknown>): string {
  const kvLines = Object.entries(entry).map(([key, value]) => {
    if (typeof value === "string") {
      return `    ${key}: ${quoteYamlString(value)}`;
    }
    return `    ${key}: ${value}`;
  });
  const [first, ...rest] = kvLines;
  return `  - ${first.trimStart()}\n${rest.join("\n")}`;
}

function resolveModelEntries(
  providers: DesktopProviderWithSecret[],
  presets: Record<string, ProviderPreset>,
) {
  return providers.flatMap((provider) => {
    if (!provider.defaultModel.trim()) {
      return [];
    }

    const secret = provider.secret?.trim();
    const preset = presets[provider.providerType];
    const use = preset?.use ?? "langchain_openai:ChatOpenAI";
    const apiKeyField = preset?.apiKeyField ?? "api_key";
    const isOptionalApiKeyProvider = provider.providerType === "openai-compatible";

    if (!secret && !isOptionalApiKeyProvider) {
      return [];
    }

    const entry: Record<string, unknown> = {
      name: provider.defaultModel.trim(),
      display_name: `${provider.label} - ${provider.defaultModel.trim()}`,
      use,
      model: provider.defaultModel.trim(),
      request_timeout: 600.0,
      max_retries: 2,
    };

    if (secret) {
      entry[apiKeyField] = secret;
    }

    if (provider.baseUrl.trim()) {
      const baseUrlField = use.includes("patched_deepseek")
        ? "api_base"
        : "base_url";
      entry[baseUrlField] = provider.baseUrl.trim();
    }

    return [entry];
  });
}

function replaceModelsSection(configContent: string, modelsYaml: string) {
  const lines = configContent.split("\n");
  const startIndex = lines.findIndex((line) => line.startsWith("models:"));

  if (startIndex === -1) {
    return `${configContent.replace(/\s*$/, "")}\n\n${modelsYaml}\n`;
  }

  let endIndex = lines.length;
  for (let index = startIndex + 1; index < lines.length; index += 1) {
    const trimmed = lines[index]?.trim() ?? "";
    if (!trimmed) {
      continue;
    }
    if (trimmed.startsWith("#")) {
      continue;
    }
    if (TOP_LEVEL_KEY_PATTERN.test(lines[index] ?? "")) {
      endIndex = index;
      break;
    }
  }

  return [
    ...lines.slice(0, startIndex),
    modelsYaml,
    ...lines.slice(endIndex),
  ].join("\n");
}

export function buildRuntimeConfigContent(
  repoConfigContent: string,
  providers: DesktopProviderSetting[],
  presets: Record<string, ProviderPreset>,
  secrets: ProviderSecretMap = {},
) {
  const providersWithSecrets = providers.map((provider) => ({
    ...provider,
    secret: secrets[provider.apiKeyEnv],
  }));
  const modelEntries = resolveModelEntries(providersWithSecrets, presets);
  const modelsYaml =
    modelEntries.length === 0
      ? "models: []"
      : `models:\n${modelEntries.map(serializeModelEntryYaml).join("\n")}`;

  const nextContent = replaceModelsSection(repoConfigContent, modelsYaml);
  return nextContent.endsWith("\n") ? nextContent : `${nextContent}\n`;
}

export function getExpectedConfiguredModelNames(
  providers: DesktopProviderSetting[],
  presets: Record<string, ProviderPreset>,
  secrets: ProviderSecretMap = {},
) {
  return resolveModelEntries(
    providers.map((provider) => ({
      ...provider,
      secret: secrets[provider.apiKeyEnv],
    })),
    presets,
  ).map((entry) => String(entry.name));
}
