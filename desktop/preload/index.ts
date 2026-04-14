import { contextBridge, ipcRenderer } from "electron";

export type DeerDesktopBridge = {
  getAppPaths: () => Promise<unknown>;
  getConfig: () => Promise<unknown>;
  getDesktopSettings: () => Promise<unknown>;
  updateDesktopSettings: (settings: unknown) => Promise<void>;
  getSecretStatuses: () => Promise<Record<string, boolean>>;
  saveSecret: (provider: string, value: string) => Promise<void>;
  deleteSecret: (provider: string) => Promise<void>;
  saveProvider: (input: unknown) => Promise<unknown>;
  deleteProvider: (providerId: string) => Promise<unknown>;
  restartRuntime: () => Promise<void>;
};

const deerDesktop: DeerDesktopBridge = {
  getAppPaths: () => ipcRenderer.invoke("deer-desktop:get-app-paths"),
  getConfig: () => ipcRenderer.invoke("deer-desktop:get-config"),
  getDesktopSettings: () => ipcRenderer.invoke("deer-desktop:get-desktop-settings"),
  updateDesktopSettings: (settings) => ipcRenderer.invoke("deer-desktop:update-desktop-settings", settings),
  getSecretStatuses: () => ipcRenderer.invoke("deer-desktop:get-secret-statuses"),
  saveSecret: (provider, value) => ipcRenderer.invoke("deer-desktop:save-secret", provider, value),
  deleteSecret: (provider) => ipcRenderer.invoke("deer-desktop:delete-secret", provider),
  saveProvider: (input) => ipcRenderer.invoke("deer-desktop:save-provider", input),
  deleteProvider: (providerId) => ipcRenderer.invoke("deer-desktop:delete-provider", providerId),
  restartRuntime: () => ipcRenderer.invoke("deer-desktop:restart-runtime"),
};

contextBridge.exposeInMainWorld("deerDesktop", deerDesktop);
