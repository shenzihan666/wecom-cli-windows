/**
 * Electron main process entry.
 *
 * Responsibilities:
 *   - On app ready: ensure frontend/dist exists, start the backend, wait for
 *     health, then load its URL into a BrowserWindow.
 *   - On quit: stop the backend (process tree) via backend-manager.
 *   - Surface startup failures (missing uv, build error, unhealthy backend)
 *     as a visible error page instead of a blank window.
 *
 * Dev mode (NODE_ENV=development): also starts the Vite dev server and loads
 * http://localhost:5173 so HMR works. The Vite config already proxies
 * /api, /media, /ws to the backend.
 */

import { app, BrowserWindow, shell } from "electron";
import path from "node:path";
import { backendManager, BACKEND_URL, DEV_FRONTEND_URL } from "./backend-manager";

const isDev = process.env.NODE_ENV === "development" || process.argv.includes("--dev");

let mainWindow: BrowserWindow | null = null;
// Prevent the backend from being killed twice during the normal quit flow.
let shuttingDown = false;

function createWindow(loadUrl: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 640,
    title: "WeCom 私聊同步",
    backgroundColor: "#0f1419",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      // The renderer is the trusted backend-served SPA; no Node needed there.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  // Open external links (http/https) in the user's browser, not in-app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  // Surface load failures (blank window debugging) and ensure the window is
  // shown once content is ready, rather than relying on default show behavior.
  win.webContents.on("did-finish-load", () => {
    console.log(`[window] finished loading ${loadUrl}`);
    win.show();
    win.focus();
  });
  win.webContents.on("did-fail-load", (_e, code, desc, url) => {
    console.error(`[window] FAILED to load url=${url} code=${code} desc=${desc}`);
    win.show();
  });
  win.webContents.on("render-process-gone", (_e, details) => {
    console.error(`[window] render-process-gone: ${JSON.stringify(details)}`);
  });

  win.loadURL(loadUrl);

  return win;
}

/**
 * Show a self-contained error page instead of a blank window when something
 * goes wrong during startup. Keeps the content inline (no external assets)
 * so it renders even with no backend/dist available.
 */
function showErrorWindow(title: string, detail: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 640,
    height: 420,
    resizable: false,
    title,
    backgroundColor: "#0f1419",
  });
  const escaped = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const html = `<!doctype html><html><head><meta charset="utf-8">
    <style>
      :root { color-scheme: dark; }
      body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
             margin: 0; padding: 32px; background:#0f1419; color:#e5e7eb; }
      h1 { font-size: 18px; color:#f87171; margin:0 0 16px; }
      p { font-size: 14px; line-height:1.6; white-space:pre-wrap;
          color:#cbd5e1; margin:0 0 12px; }
      code { background:#1e293b; padding:2px 6px; border-radius:4px; color:#fbbf24; }
    </style></head>
    <body>
    <h1>${escaped(title)}</h1>
    <p>${escaped(detail)}</p>
    </body></html>`;
  win.loadURL("data:text/html;charset=utf-8," + encodeURIComponent(html));
  return win;
}

// Guard against double-bootstrap: on macOS both `whenReady` and the initial
// `activate` event can fire during the same launch. Without this, start() runs
// twice, spawns two backends, and the second one hits the port-reuse path.
let bootstrapping = false;
let bootstrapped = false;

async function bootstrap(): Promise<void> {
  if (bootstrapping || bootstrapped) return;
  bootstrapping = true;
  try {
    if (!isDev) {
      // Production path: backend serves the prebuilt SPA.
      await backendManager.ensureFrontendDist();
    }
    // `start()` returns the URL to load — use it instead of guessing from
    // isDev, because it may take the port-reuse fast path (returning the
    // backend URL even in dev if an existing backend is detected).
    const target = await backendManager.start({
      devFrontend: isDev,
      onLog: (line) => console.log(`[backend] ${line}`),
    });

    mainWindow = createWindow(target);
    bootstrapped = true;
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    console.error("[main] bootstrap failed:", detail);
    mainWindow = showErrorWindow("启动失败", detail);
  } finally {
    bootstrapping = false;
  }
}

// --- App lifecycle -------------------------------------------------------

app.whenReady().then(bootstrap);

app.on("activate", () => {
  // macOS: re-create a window when the dock icon is clicked and none are open.
  if (BrowserWindow.getAllWindows().length === 0) {
    bootstrap();
  }
});

async function shutdown(): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  try {
    await backendManager.stop();
  } catch (err) {
    console.error("[main] backend stop error:", err);
  }
}

// Quit when all windows are closed, except on macOS (standard platform UX).
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    void shutdown().finally(() => app.quit());
  }
});

app.on("before-quit", (event) => {
  if (!shuttingDown) {
    event.preventDefault();
    void shutdown().finally(() => app.quit());
  }
});
