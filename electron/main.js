/**
 * DeerFlow Desktop - Thin Electron Wrapper
 * 
 * A minimal Electron wrapper that loads the DeerFlow web UI from localhost:2026.
 * This is a standalone wrapper that does not modify DeerFlow core code.
 * 
 * Licensed under MIT (same as DeerFlow)
 */

const { app, BrowserWindow, shell } = require('electron');
const path = require('path');

const DEERFLOW_URL = 'http://localhost:2026';
const HEALTH_CHECK_URL = 'http://localhost:2026/health';
const POLL_INTERVAL = 2000;

let mainWindow = null;
let backendCheckInterval = null;

/**
 * Create the main application window
 */
function createWindow() {
  const windowOptions = {
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    title: 'DeerFlow',
    // Use default title bar to avoid overlap with window controls
    titleBarStyle: 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      webSecurity: true
    }
  };

  mainWindow = new BrowserWindow(windowOptions);

  // Handle external links in system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  // Handle navigation within the app
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('http://localhost:')) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  // Check backend and load
  loadDeerFlow();

  // Handle window closed
  mainWindow.on('closed', () => {
    mainWindow = null;
    stopBackendPolling();
  });
}

/**
 * Check if DeerFlow backend is healthy
 */
async function checkBackendHealth() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    
    const response = await fetch(HEALTH_CHECK_URL, { 
      signal: controller.signal
    });
    clearTimeout(timeout);
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Load DeerFlow UI or show waiting screen
 */
async function loadDeerFlow() {
  const isReady = await checkBackendHealth();
  
  if (isReady && mainWindow) {
    stopBackendPolling();
    mainWindow.loadURL(DEERFLOW_URL);
  } else if (mainWindow) {
    showWaitingScreen();
    startBackendPolling();
  }
}

/**
 * Show waiting screen for backend
 */
function showWaitingScreen() {
  if (!mainWindow) return;
  
  const waitingHtml = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100vh;
          background: #0a0a0a;
          color: #e5e5e5;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
          text-align: center;
          padding: 20px;
        }
        .spinner {
          width: 40px;
          height: 40px;
          border: 3px solid #262626;
          border-top-color: #3b82f6;
          border-radius: 50%;
          animation: spin 1s linear infinite;
          margin-bottom: 20px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        h1 { font-size: 18px; font-weight: 500; margin-bottom: 8px; }
        p { color: #737373; font-size: 14px; line-height: 1.5; max-width: 400px; }
        code {
          background: #262626;
          padding: 4px 8px;
          border-radius: 4px;
          font-family: 'Menlo', 'Monaco', monospace;
          font-size: 12px;
          color: #e5e5e5;
        }
        .button {
          margin-top: 20px;
          padding: 10px 20px;
          background: #262626;
          border: 1px solid #404040;
          border-radius: 6px;
          color: #e5e5e5;
          font-size: 13px;
          cursor: pointer;
          transition: background 0.2s;
        }
        .button:hover { background: #333; }
      </style>
    </head>
    <body>
      <div class="spinner"></div>
      <h1>Waiting for DeerFlow backend...</h1>
      <p>Please start the backend first:</p>
      <p style="margin-top: 12px;"><code>make docker-start</code></p>
      <button class="button" onclick="checkAgain()">Check Again</button>
      <script>
        function checkAgain() {
          location.reload();
        }
        // Auto-check every 3 seconds
        setTimeout(() => location.reload(), 3000);
      </script>
    </body>
    </html>
  `;
  
  const dataUrl = 'data:text/html;charset=utf-8,' + encodeURIComponent(waitingHtml);
  mainWindow.loadURL(dataUrl);
}

/**
 * Start polling for backend availability
 */
function startBackendPolling() {
  stopBackendPolling();
  backendCheckInterval = setInterval(async () => {
    if (!mainWindow) {
      stopBackendPolling();
      return;
    }
    const isReady = await checkBackendHealth();
    if (isReady) {
      loadDeerFlow();
    }
  }, POLL_INTERVAL);
}

/**
 * Stop backend polling
 */
function stopBackendPolling() {
  if (backendCheckInterval) {
    clearInterval(backendCheckInterval);
    backendCheckInterval = null;
  }
}

// ============================================================================
// Electron Lifecycle
// ============================================================================

app.whenReady().then(() => {
  // Small delay to ensure app is fully ready
  setTimeout(createWindow, 100);
});

app.on('window-all-closed', () => {
  stopBackendPolling();
  app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('before-quit', () => {
  stopBackendPolling();
});

// Prevent new window creation
app.on('web-contents-created', (_, contents) => {
  contents.on('new-window', (event) => {
    event.preventDefault();
  });
});
