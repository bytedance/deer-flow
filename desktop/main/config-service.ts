import type { DesktopProviderSetting, DesktopSettings } from "./config.js";

export type DesktopConfigSnapshot = {
  defaultModel: string | null;
  providers: DesktopProviderSetting[];
  secretStatuses: Record<string, boolean>;
  effectiveModels: string[];
};

export type SaveDesktopProviderInput = {
  provider: DesktopProviderSetting;
  apiKey?: string | null | undefined;
};

type SaveDesktopProviderOptions = {
  current: DesktopSettings;
  input: SaveDesktopProviderInput;
  setSettings: (settings: DesktopSettings) => Promise<void>;
  saveSecret: (provider: string, value: string) => Promise<void>;
  deleteSecret: (provider: string) => Promise<void>;
  syncConfig: () => Promise<void>;
};

type DeleteDesktopProviderOptions = {
  current: DesktopSettings;
  providerId: string;
  setSettings: (settings: DesktopSettings) => Promise<void>;
  deleteSecret: (provider: string) => Promise<void>;
  syncConfig: () => Promise<void>;
};

export function buildDesktopConfigSnapshot(
  settings: DesktopSettings,
  secretStatuses: Record<string, boolean>,
  effectiveModels: string[],
): DesktopConfigSnapshot {
  return {
    defaultModel: settings.defaultModel,
    providers: settings.providers,
    secretStatuses,
    effectiveModels,
  };
}

export function upsertDesktopProvider(
  settings: DesktopSettings,
  provider: DesktopProviderSetting,
): DesktopSettings {
  const nextProviders = [...settings.providers];
  const existingIndex = nextProviders.findIndex((item) => item.id === provider.id);

  if (existingIndex >= 0) {
    nextProviders[existingIndex] = provider;
  } else {
    nextProviders.push(provider);
  }

  return {
    ...settings,
    providers: nextProviders,
  };
}

export function removeDesktopProvider(
  settings: DesktopSettings,
  providerId: string,
): {
  nextSettings: DesktopSettings;
  removedProvider: DesktopProviderSetting | null;
} {
  const removedProvider =
    settings.providers.find((provider) => provider.id === providerId) ?? null;

  return {
    nextSettings: {
      ...settings,
      providers: settings.providers.filter((provider) => provider.id !== providerId),
    },
    removedProvider,
  };
}

export async function saveDesktopProvider({
  current,
  input,
  setSettings,
  saveSecret,
  deleteSecret,
  syncConfig,
}: SaveDesktopProviderOptions) {
  const existingProvider =
    current.providers.find((provider) => provider.id === input.provider.id) ?? null;

  if (existingProvider && existingProvider.apiKeyEnv !== input.provider.apiKeyEnv) {
    throw new Error("Updating apiKeyEnv for an existing provider is not supported");
  }

  const nextSettings = upsertDesktopProvider(current, input.provider);
  await setSettings(nextSettings);

  try {
    if (input.apiKey !== undefined) {
      if (input.apiKey && input.apiKey.trim()) {
        await saveSecret(input.provider.apiKeyEnv, input.apiKey.trim());
      } else {
        await deleteSecret(input.provider.apiKeyEnv);
      }
    }

    await syncConfig();
    return nextSettings;
  } catch (error) {
    await setSettings(current);
    throw error;
  }
}

export async function deleteDesktopProvider({
  current,
  providerId,
  setSettings,
  deleteSecret,
  syncConfig,
}: DeleteDesktopProviderOptions) {
  const { nextSettings, removedProvider } = removeDesktopProvider(current, providerId);

  await setSettings(nextSettings);

  try {
    if (removedProvider) {
      await deleteSecret(removedProvider.apiKeyEnv);
    }

    await syncConfig();
    return { nextSettings, removedProvider };
  } catch (error) {
    await setSettings(current);
    throw error;
  }
}
