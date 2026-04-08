import { contextBridge, ipcRenderer } from "electron";

export type DeerDesktopBridge = {
  getAppPaths: () => Promise<unknown>;
  getDesktopSettings: () => Promise<unknown>;
  updateDesktopSettings: (settings: unknown) => Promise<void>;
  getSecretStatuses: () => Promise<Record<string, boolean>>;
  saveSecret: (provider: string, value: string) => Promise<void>;
  deleteSecret: (provider: string) => Promise<void>;
  restartRuntime: () => Promise<void>;
};

const deerDesktop: DeerDesktopBridge = {
  getAppPaths: () => ipcRenderer.invoke("deer-desktop:get-app-paths"),
  getDesktopSettings: () => ipcRenderer.invoke("deer-desktop:get-desktop-settings"),
  updateDesktopSettings: (settings) => ipcRenderer.invoke("deer-desktop:update-desktop-settings", settings),
  getSecretStatuses: () => ipcRenderer.invoke("deer-desktop:get-secret-statuses"),
  saveSecret: (provider, value) => ipcRenderer.invoke("deer-desktop:save-secret", provider, value),
  deleteSecret: (provider) => ipcRenderer.invoke("deer-desktop:delete-secret", provider),
  restartRuntime: () => ipcRenderer.invoke("deer-desktop:restart-runtime"),
};

contextBridge.exposeInMainWorld("deerDesktop", deerDesktop);
