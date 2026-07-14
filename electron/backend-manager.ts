/**
 * Backend process manager for the Electron main process.
 *
 * Owns the lifecycle of the Python FastAPI backend:
 *   1. (optional) ensure `frontend/dist` exists by running `pnpm build`
 *   2. spawn `uv run python backend/run.py` with the configured port
 *   3. poll `GET /api/status` until the server answers (health check)
 *   4. on shutdown, tear down the whole process tree (cross-platform)
 *
 * Kept dependency-light: only `tree-kill` + Node stdlib. All platform
 * differences (spawn shell on Windows, port detection) are centralised here
 * so `main.ts` stays a thin orchestrator.
 */

import { spawn, ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import treeKill from "tree-kill";

/** Fixed port — matches the backend default and `frontend/vite.config.ts` proxy. */
export const BACKEND_PORT = 8765;
export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

/** Vite dev server (dev mode only). Matches `frontend/vite.config.ts`. */
const DEV_FRONTEND_PORT = 5173;
export const DEV_FRONTEND_URL = `http://127.0.0.1:${DEV_FRONTEND_PORT}`;

/** Project root = parent of this compiled file's source dir (electron/ → root). */
export const PROJECT_ROOT = path.resolve(__dirname, "..");

const MAX_HEALTH_PROBE_MS = 45_000;
// Vite's first compile can take a while; give it more room than the backend.
const MAX_VITE_PROBE_MS = 60_000;
const PROBE_INTERVAL_MS = 500;

export interface StartOptions {
  /** When true, also spawn `pnpm dev` for the frontend and load the Vite server. */
  devFrontend?: boolean;
  /** Called with each backend stdout/stderr line, for the splash/log window. */
  onLog?: (line: string) => void;
}

class BackendManager {
  private proc: ChildProcess | null = null;
  private frontendProc: ChildProcess | null = null;
  private killing = false;

  /** True if something is already listening on the backend port. */
  isPortInUse(port = BACKEND_PORT): Promise<boolean> {
    return new Promise((resolve) => {
      const tester = net
        .createServer()
        .once("error", () => resolve(true))
        .once("listening", () => {
          tester.close(() => resolve(false));
        });
      tester.listen(port, "127.0.0.1");
    });
  }

  /**
   * Make sure `frontend/dist/index.html` exists; if not, run the frontend
   * build. The backend serves this dir in production mode, so a missing dist
   * would render as a blank page.
   */
  async ensureFrontendDist(): Promise<void> {
    const distIndex = path.join(PROJECT_ROOT, "frontend", "dist", "index.html");
    if (existsSync(distIndex)) return;

    this.log("frontend/dist missing — building it once (this can take a few seconds)…");
    await this.runToCompletion("pnpm", ["build"], path.join(PROJECT_ROOT, "frontend"));
    if (!existsSync(distIndex)) {
      throw new Error("Frontend build finished but frontend/dist/index.html still not found.");
    }
    this.log("Frontend build ready.");
  }

  /**
   * Start the backend (and optionally the Vite dev server) and wait until the
   * backend answers health checks. Resolves with the URL to load.
   *
   * If the port is already taken we assume a previous instance is still alive
   * and just reuse it rather than fighting over the port.
   */
  async start(opts: StartOptions = {}): Promise<string> {
    const alreadyUp = await this.isPortInUse();
    if (alreadyUp) {
      // Verify it's actually our backend (responds on /api/status), not a
      // random process squatting on the port.
      const healthy = await this.probeUrl(`${BACKEND_URL}/api/status`, 1500);
      if (healthy) {
        this.log(`Port ${BACKEND_PORT} already serving the backend — reusing it.`);
        return BACKEND_URL;
      }
      throw new Error(
        `Port ${BACKEND_PORT} is in use by another program and did not respond as the backend. ` +
          `Free it or change BACKEND_PORT.`,
      );
    }

    if (opts.devFrontend) {
      // Kick off Vite first so it has time to boot while the backend starts;
      // they're awaited in parallel below.
      this.startFrontendDev(opts.onLog);
    }

    this.spawnBackend(opts.onLog);
    await this.waitForHealth(opts.onLog);

    if (opts.devFrontend) {
      // Don't load the window until Vite is actually answering — otherwise the
      // window opens to ERR_CONNECTION_REFUSED and stays blank for a beat.
      const viteOk = await this.waitForUrl(
        DEV_FRONTEND_URL,
        "Vite dev server",
        opts.onLog,
        {
          timeoutMs: MAX_VITE_PROBE_MS,
          onTick: () => {
            // If Vite died mid-boot, surface it immediately instead of polling a dead
            // port for the full timeout.
            if (this.frontendProc && this.frontendProc.exitCode !== null && !this.killing) {
              throw new Error(
                "Vite dev server exited before becoming ready. " +
                  "See the [vite] log lines above for the cause.",
              );
            }
          },
        },
      );
      if (!viteOk) {
        throw new Error(
          `Vite dev server did not become ready within ${MAX_VITE_PROBE_MS / 1000}s. ` +
            `Run \`pnpm --filter ./frontend dev\` manually to see the error.`,
        );
      }
      return DEV_FRONTEND_URL;
    }

    return BACKEND_URL;
  }

  /** Tear down backend (+ frontend dev server) process trees. Safe to call twice. */
  async stop(): Promise<void> {
    if (this.killing) return;
    this.killing = true;

    const targets: Array<[ChildProcess | null, string]> = [
      [this.frontendProc, "frontend dev"],
      [this.proc, "backend"],
    ];
    for (const [p, label] of targets) {
      if (p && p.pid) {
        await this.killTree(p.pid, label);
      }
    }
    this.frontendProc = null;
    this.proc = null;
    this.killing = false;
  }

  // --- internals ---------------------------------------------------------

  private spawnBackend(onLog?: (line: string) => void): void {
    const isWin = process.platform === "win32";
    // `uv` is a single binary on macOS/Linux; on Windows `spawn` needs
    // shell:true (or the `.exe`/`.cmd`) to resolve it off PATH.
    const child = spawn("uv", ["run", "python", "backend/run.py"], {
      cwd: PROJECT_ROOT,
      env: {
        ...process.env,
        // Match `Settings.port` in backend/app/config.py (pydantic-settings
        // maps the `PORT` env var to the `port` field). `host` stays 127.0.0.1.
        PORT: String(BACKEND_PORT),
        HOST: "127.0.0.1",
      },
      shell: isWin,
      windowsHide: true,
    });
    this.proc = child;

    const pipe = (stream: NodeJS.ReadableStream | null) => {
      if (!stream) return;
      stream.setEncoding("utf8");
      stream.on("data", (chunk: string) => {
        for (const line of chunk.split(/\r?\n/)) {
          if (line) {
            this.log(line, onLog);
          }
        }
      });
    };
    pipe(child.stdout);
    pipe(child.stderr);

    child.on("exit", (code, signal) => {
      if (!this.killing) {
        // Unexpected exit while we still think it's running.
        this.log(
          `Backend exited unexpectedly (code=${code} signal=${signal}).`,
          onLog,
        );
      }
    });
  }

  private startFrontendDev(onLog?: (line: string) => void): void {
    const isWin = process.platform === "win32";
    this.log("Starting Vite dev server (frontend)…", onLog);
    // Run `pnpm dev` from inside frontend/ rather than `pnpm --filter ./frontend dev` from the root:
    // the filter form requires a pnpm workspace declaration the root doesn't have, and would silently
    // "No projects matched" when there is none.
    const child = spawn("pnpm", ["dev"], {
      cwd: path.join(PROJECT_ROOT, "frontend"),
      env: process.env,
      shell: isWin,
      windowsHide: true,
    });
    this.frontendProc = child;

    // Pipe Vite's output so failures (port conflict, missing dep, config error)
    // are visible instead of silently swallowed into ERR_CONNECTION_REFUSED.
    const pipe = (stream: NodeJS.ReadableStream | null) => {
      if (!stream) return;
      stream.setEncoding("utf8");
      stream.on("data", (chunk: string) => {
        for (const line of chunk.split(/\r?\n/)) {
          if (line) this.log(`[vite] ${line}`, onLog);
        }
      });
    };
    pipe(child.stdout);
    pipe(child.stderr);

    child.on("exit", (code, signal) => {
      if (!this.killing) {
        this.log(`Vite dev server exited (code=${code} signal=${signal}).`, onLog);
      }
    });
  }

  /** Poll /api/status until 200 or timeout. */
  private async waitForHealth(onLog?: (line: string) => void): Promise<void> {
    this.log("Waiting for backend to be ready…", onLog);
    const ok = await this.waitForUrl(`${BACKEND_URL}/api/status`, "backend", onLog, {
      onTick: () => {
        // Bail early if the backend died mid-boot instead of waiting the full
        // timeout — the error message is more actionable that way.
        if (this.proc && this.proc.exitCode !== null && !this.killing) {
          throw new Error("Backend process exited before becoming healthy.");
        }
      },
    });
    if (!ok) {
      throw new Error(
        `Backend did not become healthy within ${MAX_HEALTH_PROBE_MS / 1000}s. ` +
          `Check that 'uv', Python 3.11+ and wecom-cli are installed.`,
      );
    }
    this.log("Backend is ready.", onLog);
  }

  /**
   * Poll `url` until it answers 200, or the deadline elapses. Resolves false
   * on timeout (caller decides whether that's fatal). Used for both the
   * backend `/api/status` check and the Vite dev server readiness check.
   */
  private async waitForUrl(
    url: string,
    label: string,
    onLog?: (line: string) => void,
    { onTick, timeoutMs = MAX_HEALTH_PROBE_MS }: { onTick?: () => void; timeoutMs?: number } = {},
  ): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    this.log(`Waiting for ${label}…`, onLog);
    while (Date.now() < deadline) {
      onTick?.();
      if (await this.probeUrl(url, PROBE_INTERVAL_MS)) {
        this.log(`${label[0].toUpperCase()}${label.slice(1)} is ready.`, onLog);
        return true;
      }
      await sleep(PROBE_INTERVAL_MS);
    }
    return false;
  }

  private probeUrl(url: string, timeoutMs: number): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { signal: controller.signal })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => clearTimeout(timer));
  }

  private killTree(pid: number, label: string): Promise<void> {
    return new Promise((resolve) => {
      treeKill(pid, "SIGTERM", (err) => {
        if (err) {
          // SIGTERM may race with an already-dying process; fall back to KILL.
          treeKill(pid, "SIGKILL", () => resolve());
        } else {
          resolve();
        }
      });
      this.log(`Stopped ${label} (pid ${pid}).`);
    });
  }

  private runToCompletion(
    cmd: string,
    args: string[],
    cwd: string,
    onLog?: (line: string) => void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const isWin = process.platform === "win32";
      const child = spawn(cmd, args, {
        cwd,
        env: process.env,
        shell: isWin,
        windowsHide: true,
      });
      const pipe = (stream: NodeJS.ReadableStream | null) => {
        if (!stream) return;
        stream.setEncoding("utf8");
        stream.on("data", (chunk: string) => {
          for (const line of chunk.split(/\r?\n/)) {
            if (line) this.log(line, onLog);
          }
        });
      };
      pipe(child.stdout);
      pipe(child.stderr);
      child.on("error", reject);
      child.on("exit", (code) =>
        code === 0 ? resolve() : reject(new Error(`'${cmd} ${args.join(" ")}' exited with ${code}`)),
      );
    });
  }

  private log(line: string, onLog?: (line: string) => void): void {
    // Route through the caller's logger if provided; otherwise fall back to
    // the main-process console. Doing both would duplicate every line.
    if (onLog) {
      onLog(line);
    } else {
      console.log(`[backend] ${line}`);
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export const backendManager = new BackendManager();
