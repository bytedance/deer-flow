import path from "node:path";
import { fileURLToPath } from "node:url";

import { app, BrowserWindow, dialog } from "electron";

app.disableHardwareAcceleration();

import {
  ensureDesktopConfigFiles,
  ensureDesktopDirectories,
  readDesktopSettings,
  writeDesktopSettings,
} from "./config.js";
import { registerDesktopIpc } from "./ipc.js";
import { getDesktopPaths } from "./paths.js";
import { createRuntimeProcessController } from "./processes.js";
import { configureSecretsStore } from "./secrets.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "../../..");
const userData = app.getPath("userData");
const paths = getDesktopPaths(userData, repoRoot);
const runtime = createRuntimeProcessController({ repoRoot, paths });

let runtimeStarted = false;
let ipcRegistered = false;
let windowCreationPromise: Promise<void> | null = null;
let mainWindow: BrowserWindow | null = null;

async function ensureRuntime() {
  await ensureDesktopDirectories(paths);

  const settings = await readDesktopSettings(paths);
  await ensureDesktopConfigFiles(paths, settings);

  configureSecretsStore(paths.secretsPath);

  if (!ipcRegistered) {
    registerDesktopIpc({
      paths,
      runtime,
      getSettings: () => readDesktopSettings(paths),
      setSettings: async (nextSettings: Awaited<ReturnType<typeof readDesktopSettings>>) => {
        await writeDesktopSettings(paths, nextSettings);
        await ensureDesktopConfigFiles(paths, nextSettings);
      },
    });
    ipcRegistered = true;
  }

  if (!runtimeStarted) {
    await runtime.start();
    runtimeStarted = true;
  }
}

function startupPageHtml(title: string, body: string) {
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>DeerFlow Desktop</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 0; background: #0b0b0c; color: #f5f5f5; }
      .wrap { max-width: 760px; margin: 80px auto; padding: 32px; }
      h1 { font-size: 28px; margin-bottom: 12px; }
      p, li { line-height: 1.6; color: #d4d4d8; }
      code, pre { background: #18181b; color: #fafafa; border-radius: 8px; }
      code { padding: 2px 6px; }
      pre { padding: 16px; overflow: auto; white-space: pre-wrap; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h1>${title}</h1>
      <pre>${body}</pre>
    </div>
  </body>
</html>`;
}

function startupLoadingHtml() {
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>DeerFlow Desktop</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: #292929;
      }

      svg {
        width: 56px;
        height: 56px;
        animation: spin 1s linear infinite;
      }

      circle {
        fill: none;
        stroke: #a1a1aa;
        stroke-linecap: round;
        stroke-width: 4;
        stroke-dasharray: 90;
        stroke-dashoffset: 60;
      }

      @keyframes spin {
        to { transform: rotate(360deg); }
      }
    </style>
  </head>
  <body>
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <circle cx="24" cy="24" r="18"></circle>
    </svg>
  </body>
</html>`;
}

async function createMainWindow() {
  if (windowCreationPromise) {
    await windowCreationPromise;
    return;
  }

  windowCreationPromise = (async () => {
    await ensureRuntime();

    mainWindow = new BrowserWindow({
      width: 1440,
      height: 960,
      show: true,
      backgroundColor: "#292929",
      webPreferences: {
        preload: path.join(__dirname, "../../preload/index.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });

    mainWindow.on("closed", () => {
      mainWindow = null;
    });

    mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription) => {
      console.error("did-fail-load", errorCode, errorDescription);
    });

    mainWindow.webContents.on("render-process-gone", (_event, details) => {
      console.error("render-process-gone", details.reason, details.exitCode);
    });

    mainWindow.webContents.on("console-message", (_event, level, message) => {
      console.log("renderer-console", level, message);
    });

    await mainWindow.loadURL(
      `data:text/html;charset=utf-8,${encodeURIComponent(startupLoadingHtml())}`,
    );


    try {
      await runtime.waitUntilReady();
      await mainWindow.loadURL(runtime.getURL());
      mainWindow.show();
      mainWindow.focus();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await mainWindow.loadURL(
        `data:text/html;charset=utf-8,${encodeURIComponent(
          startupPageHtml(
            "DeerFlow Desktop startup failed",
            `Desktop startup requires repo-local runtime files and a healthy local runtime.\n\nRequired files:\n- config.yaml\n- extensions_config.json\n- .env\n\nBootstrap commands:\npython3 scripts/configure.py\ncp extensions_config.example.json extensions_config.json\n\nCurrent error:\n${message}`,
          ),
        )}`,
      );
    }
  })().finally(() => {
    windowCreationPromise = null;
  });

  await windowCreationPromise;
}

app.whenReady().then(() => createMainWindow()).catch(async (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  await dialog.showErrorBox("DeerFlow Desktop startup failed", message);
  app.quit();
});

app.on("before-quit", () => {
  runtimeStarted = false;
  void runtime.stop();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (mainWindow === null) {
    void createMainWindow();
  }
});
