import { ipcMain } from "electron";

import type { DesktopPaths } from "./paths.js";
import type { DesktopSettings } from "./config.js";
import type { RuntimeProcessController } from "./processes.js";
import { deleteSecret, getSecretStatuses, saveSecret } from "./secrets.js";

export function registerDesktopIpc(options: {
  paths: DesktopPaths;
  mode: "shared" | "bundled";
  getSettings: () => Promise<DesktopSettings>;
  setSettings: (settings: DesktopSettings) => Promise<void>;
  runtime: RuntimeProcessController;
}) {
  ipcMain.handle("deer-desktop:get-app-paths", async () => ({
    ...options.paths,
    mode: options.mode,
  }));
  ipcMain.handle("deer-desktop:get-desktop-settings", async () => options.getSettings());
  ipcMain.handle("deer-desktop:update-desktop-settings", async (_event, partial: Partial<DesktopSettings>) => {
    const current = await options.getSettings();
    await options.setSettings({ ...current, ...partial });
  });
  ipcMain.handle("deer-desktop:get-secret-statuses", async () => {
    const settings = await options.getSettings();
    return getSecretStatuses(settings.providers.map((provider) => provider.apiKeyEnv));
  });
  ipcMain.handle("deer-desktop:save-secret", async (_event, provider: string, value: string) => {
    await saveSecret(provider, value);
    await options.runtime.restart();
  });
  ipcMain.handle("deer-desktop:delete-secret", async (_event, provider: string) => {
    await deleteSecret(provider);
    await options.runtime.restart();
  });
  ipcMain.handle("deer-desktop:restart-runtime", async () => {
    await options.runtime.restart();
  });
}
