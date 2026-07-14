/**
 * Preload script — the bridge between the renderer (the backend-served SPA)
 * and the main process.
 *
 * Currently minimal: the SPA talks to the backend directly over HTTP/WS, so
 * it doesn't strictly need any Electron APIs. This file exists to:
 *   - keep `contextIsolation` on (a hardening default) while still allowing
 *     future privileged operations to be added behind a vetted surface, and
 *   - expose the backend URL / versions for an eventual "About" panel.
 */

import { contextBridge } from "electron";
import { BACKEND_URL } from "./backend-manager";

contextBridge.exposeInMainWorld("electronAPI", {
  backendUrl: BACKEND_URL,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
});
