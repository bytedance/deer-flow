import electron from "electron";
import type { BrowserWindow } from "electron";

import { getDevtoolsAccelerators } from "./devtools-accelerators.js";

const { globalShortcut } = electron;

export function registerDevtoolsShortcuts(window: BrowserWindow) {
  const accelerators = getDevtoolsAccelerators();

  const registered = accelerators.filter((accelerator) =>
    globalShortcut.register(accelerator, () => {
      if (!window.isDestroyed()) {
        window.webContents.toggleDevTools();
      }
    }),
  );

  return () => {
    for (const accelerator of registered) {
      globalShortcut.unregister(accelerator);
    }
  };
}
