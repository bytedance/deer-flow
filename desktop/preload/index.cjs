const { contextBridge, ipcRenderer } = require("electron");

const deerDesktop = {
  getAppPaths: () => ipcRenderer.invoke("deer-desktop:get-app-paths"),
  getDesktopSettings: () => ipcRenderer.invoke("deer-desktop:get-desktop-settings"),
  updateDesktopSettings: (settings) =>
    ipcRenderer.invoke("deer-desktop:update-desktop-settings", settings),
  getSecretStatuses: () => ipcRenderer.invoke("deer-desktop:get-secret-statuses"),
  saveSecret: (provider, value) =>
    ipcRenderer.invoke("deer-desktop:save-secret", provider, value),
  deleteSecret: (provider) =>
    ipcRenderer.invoke("deer-desktop:delete-secret", provider),
  restartRuntime: () => ipcRenderer.invoke("deer-desktop:restart-runtime"),
};

contextBridge.exposeInMainWorld("deerDesktop", deerDesktop);
