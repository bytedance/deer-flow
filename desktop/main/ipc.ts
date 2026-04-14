import { ipcMain } from "electron";

import type { DesktopPaths } from "./paths.js";
import type { DesktopSettings } from "./config.js";
import type { RuntimeProcessController } from "./processes.js";
import { PROVIDER_PRESETS } from "./config.js";
import {
  buildDesktopConfigSnapshot,
  deleteDesktopProvider,
  saveDesktopProvider,
  type SaveDesktopProviderInput,
} from "./config-service.js";
import { getExpectedConfiguredModelNames } from "./runtime-config.js";
import { deleteSecret, getSecret, getSecretStatuses, saveSecret } from "./secrets.js";

export function registerDesktopIpc(options: {
  paths: DesktopPaths;
  mode: "shared" | "bundled";
  getSettings: () => Promise<DesktopSettings>;
  setSettings: (settings: DesktopSettings) => Promise<void>;
  runtime: RuntimeProcessController;
}) {
  async function getDesktopConfig() {
    const settings = await options.getSettings();
    const secretStatuses = await getSecretStatuses(
      settings.providers.map((provider) => provider.apiKeyEnv),
    );
    const secrets = Object.fromEntries(
      await Promise.all(
        settings.providers.map(async (provider) => [
          provider.apiKeyEnv,
          (await getSecret(provider.apiKeyEnv)) ?? undefined,
        ] as const),
      ),
    );
    const effectiveModels = getExpectedConfiguredModelNames(
      settings.providers,
      PROVIDER_PRESETS,
      secrets,
    );

    return buildDesktopConfigSnapshot(settings, secretStatuses, effectiveModels);
  }

  ipcMain.handle("deer-desktop:get-app-paths", async () => ({
    ...options.paths,
    mode: options.mode,
  }));
  ipcMain.handle("deer-desktop:get-desktop-settings", async () => options.getSettings());
  ipcMain.handle("deer-desktop:get-config", async () => getDesktopConfig());
  ipcMain.handle("deer-desktop:update-desktop-settings", async (_event, partial: Partial<DesktopSettings>) => {
    const current = await options.getSettings();
    await options.setSettings({ ...current, ...partial });
    await options.runtime.syncConfig();
  });
  ipcMain.handle("deer-desktop:get-secret-statuses", async () => {
    const settings = await options.getSettings();
    return getSecretStatuses(settings.providers.map((provider) => provider.apiKeyEnv));
  });
  ipcMain.handle("deer-desktop:save-secret", async (_event, provider: string, value: string) => {
    await saveSecret(provider, value);
    await options.runtime.syncConfig();
  });
  ipcMain.handle("deer-desktop:delete-secret", async (_event, provider: string) => {
    await deleteSecret(provider);
    await options.runtime.syncConfig();
  });
  ipcMain.handle("deer-desktop:save-provider", async (_event, input: SaveDesktopProviderInput) => {
    const current = await options.getSettings();

    await saveDesktopProvider({
      current,
      input,
      setSettings: options.setSettings,
      saveSecret,
      deleteSecret,
      syncConfig: () => options.runtime.syncConfig(),
    });

    return getDesktopConfig();
  });
  ipcMain.handle("deer-desktop:delete-provider", async (_event, providerId: string) => {
    const current = await options.getSettings();

    await deleteDesktopProvider({
      current,
      providerId,
      setSettings: options.setSettings,
      deleteSecret,
      syncConfig: () => options.runtime.syncConfig(),
    });

    return getDesktopConfig();
  });
  ipcMain.handle("deer-desktop:restart-runtime", async () => {
    await options.runtime.restart();
  });
}
