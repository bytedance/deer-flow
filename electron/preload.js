/**
 * DeerFlow Desktop - Preload Script
 * 
 * Provides a secure bridge between the renderer process (DeerFlow web UI)
 * and the main process. This runs in a context-isolated world.
 * 
 * Licensed under MIT (same as DeerFlow)
 */

const { contextBridge } = require('electron');

/**
 * Expose minimal API to the renderer process
 * All methods are read-only and safe
 */
contextBridge.exposeInMainWorld('deerflowDesktop', {
  /**
   * Platform information (read-only)
   */
  platform: process.platform,
  
  /**
   * Version information
   */
  versions: {
    deerflow: '2.x',
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome
  },
  
  /**
   * Check if running in Electron wrapper
   */
  isElectron: true
});
