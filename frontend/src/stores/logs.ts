/**
 * Real-time log store (module-level singleton, no Pinia).
 *
 * One WebSocket per account id tails the backend's `data/logs/{id}.log`.
 * Logs are buffered per account in a `shallowRef` so pushes to account A don't
 * re-render panels subscribed to account B. The buffer caps at `maxLogs` and
 * drops the oldest entries to bound memory during long runs.
 *
 * Connection lifecycle mirrors the reference project: client-driven ping/pong
 * heartbeat (25s / 35s timeout) plus exponential-backoff reconnect.
 */

import { computed, shallowRef, type ShallowRef } from "vue";

export interface LogEntry {
  id: string;
  timestamp: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
  message: string;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_MAX_ATTEMPTS = 20;
const HEARTBEAT_INTERVAL_MS = 25_000;
const HEARTBEAT_TIMEOUT_MS = 35_000;
const maxLogs = 1000;

// Per-account reactive buffer. Each account gets its own shallowRef so a push
// on account A only re-renders panels subscribed to account A.
const accountLogRefs = new Map<string, ShallowRef<LogEntry[]>>();
const accountSerialsVersion = shallowRef(0);

const websockets = new Map<string, WebSocket>();

// Non-reactive bookkeeping (intentionally outside Vue's reactivity system).
const knownLogIds = new Set<string>();
const reconnectAttempts = new Map<string, number>();
const reconnectTimers = new Map<string, number>();
const intentionallyClosed = new Set<string>();
const heartbeatTimers = new Map<string, { ping: number; watchdog: number }>();
const lastPongAt = new Map<string, number>();

function ensureRef(accountId: string): ShallowRef<LogEntry[]> {
  let r = accountLogRefs.get(accountId);
  if (!r) {
    r = shallowRef<LogEntry[]>([]);
    accountLogRefs.set(accountId, r);
    accountSerialsVersion.value += 1;
  }
  return r;
}

export function getAccountLogs(accountId: string): LogEntry[] {
  return ensureRef(accountId).value;
}

export const accountsWithLogs = computed(() => {
  // Touch the version counter so this recomputes when a new account registers.
  void accountSerialsVersion.value;
  return Array.from(accountLogRefs.keys());
});

function addLog(accountId: string, entry: LogEntry): void {
  if (knownLogIds.has(entry.id)) return;
  knownLogIds.add(entry.id);

  const r = ensureRef(accountId);
  const logs = r.value;
  logs.push(entry);

  if (logs.length > maxLogs) {
    const removed = logs.splice(0, logs.length - maxLogs);
    for (const log of removed) {
      knownLogIds.delete(log.id);
    }
  }

  // Swap to a new array reference so child components receiving the array as a
  // prop see it as changed and re-run downstream computeds.
  r.value = logs.slice();
}

export function clearLogs(accountId: string): void {
  const r = accountLogRefs.get(accountId);
  if (r) {
    for (const log of r.value) {
      knownLogIds.delete(log.id);
    }
    r.value = [];
  }
}

// --- Heartbeat -------------------------------------------------------------

function stopHeartbeat(accountId: string): void {
  const t = heartbeatTimers.get(accountId);
  if (t) {
    window.clearInterval(t.ping);
    window.clearInterval(t.watchdog);
    heartbeatTimers.delete(accountId);
  }
  lastPongAt.delete(accountId);
}

function startHeartbeat(accountId: string, ws: WebSocket): void {
  stopHeartbeat(accountId);
  lastPongAt.set(accountId, Date.now());

  const ping = window.setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      try {
        ws.send("ping");
      } catch {
        // Send failure is picked up by the watchdog below.
      }
    }
  }, HEARTBEAT_INTERVAL_MS);

  const watchdog = window.setInterval(() => {
    const last = lastPongAt.get(accountId) ?? 0;
    if (Date.now() - last > HEARTBEAT_TIMEOUT_MS) {
      console.warn(`[LogStore] Heartbeat timeout for ${accountId}, forcing close`);
      try {
        ws.close(4000, "heartbeat-timeout");
      } catch {
        /* noop */
      }
    }
  }, HEARTBEAT_INTERVAL_MS);

  heartbeatTimers.set(accountId, { ping, watchdog });
}

// --- Reconnect -------------------------------------------------------------

function clearReconnectTimer(accountId: string): void {
  const t = reconnectTimers.get(accountId);
  if (t) {
    window.clearTimeout(t);
    reconnectTimers.delete(accountId);
  }
}

function scheduleReconnect(accountId: string): void {
  if (intentionallyClosed.has(accountId)) return;

  const attempts = reconnectAttempts.get(accountId) ?? 0;
  if (attempts >= RECONNECT_MAX_ATTEMPTS) {
    addLog(accountId, {
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      level: "ERROR",
      message: `日志流重连失败（已达最大尝试次数 ${attempts}）`,
    });
    return;
  }

  const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempts, RECONNECT_MAX_MS);
  reconnectAttempts.set(accountId, attempts + 1);
  clearReconnectTimer(accountId);

  const timer = window.setTimeout(() => {
    reconnectTimers.delete(accountId);
    connectLogStream(accountId);
  }, delay);
  reconnectTimers.set(accountId, timer);
}

function buildWsUrl(accountId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/logs/${encodeURIComponent(accountId)}`;
}

export function connectLogStream(accountId: string): void {
  intentionallyClosed.delete(accountId);

  const existing = websockets.get(accountId);
  if (
    existing &&
    (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }

  const ws = new WebSocket(buildWsUrl(accountId));

  ws.onopen = () => {
    reconnectAttempts.delete(accountId);
    clearReconnectTimer(accountId);
    startHeartbeat(accountId, ws);
  };

  ws.onmessage = (event) => {
    const raw = event.data;
    if (raw === "pong" || raw === "ping") {
      lastPongAt.set(accountId, Date.now());
      return;
    }
    try {
      const data = JSON.parse(raw) as {
        timestamp?: string;
        level?: string;
        message?: string;
      };
      const level = (data.level || "INFO").toUpperCase();
      addLog(accountId, {
        id: crypto.randomUUID(),
        timestamp: data.timestamp || new Date().toISOString(),
        level: (["DEBUG", "INFO", "WARNING", "ERROR"].includes(level)
          ? level
          : "INFO") as LogEntry["level"],
        message: data.message ?? "",
      });
    } catch {
      addLog(accountId, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: "INFO",
        message: typeof raw === "string" ? raw : String(raw),
      });
    }
  };

  ws.onerror = () => {
    // Errors are handled by onclose -> scheduleReconnect.
  };

  ws.onclose = (ev) => {
    websockets.delete(accountId);
    stopHeartbeat(accountId);

    if (intentionallyClosed.has(accountId)) {
      intentionallyClosed.delete(accountId);
      return;
    }

    addLog(accountId, {
      id: crypto.randomUUID(),
      timestamp: new Date().toISOString(),
      level: "WARNING",
      message: `日志流已断开 (code=${ev.code})，正在重连…`,
    });
    scheduleReconnect(accountId);
  };

  websockets.set(accountId, ws);
}

export function disconnectLogStream(accountId: string): void {
  intentionallyClosed.add(accountId);
  clearReconnectTimer(accountId);
  reconnectAttempts.delete(accountId);
  stopHeartbeat(accountId);
  const ws = websockets.get(accountId);
  if (ws) {
    try {
      ws.close(1000, "client-intentional");
    } catch {
      /* noop */
    }
    websockets.delete(accountId);
  }
}

export function disconnectAll(): void {
  for (const accountId of Array.from(websockets.keys())) {
    disconnectLogStream(accountId);
  }
}
