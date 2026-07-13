<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { fetchAccounts } from "../api";
import type { Account } from "../types";
import LogStream from "../components/LogStream.vue";
import {
  getAccountLogs,
  connectLogStream,
  disconnectLogStream,
  clearLogs,
  type LogEntry,
} from "../stores/logs";

// Toolbar filters shared across all panels.
const levelFilter = ref<"all" | "DEBUG" | "INFO" | "WARNING" | "ERROR">("all");
const searchQuery = ref("");
const autoScroll = ref(true);

// Multi-panel layout: up to 3 account log panels side by side.
const maxPanels = 3;
const panels = ref<string[]>([]);
const focusedAccountId = ref<string | null>(null);

const accounts = ref<Account[]>([]);
let timer: ReturnType<typeof setInterval> | undefined;

async function refreshAccounts(): Promise<void> {
  try {
    const data = await fetchAccounts();
    accounts.value = data.accounts;
  } catch {
    /* network errors are non-fatal here; the poll will retry */
  }
}

const activeAccountId = computed(
  () => focusedAccountId.value || panels.value[0] || null,
);

const gridColsClass = computed(() => {
  if (panels.value.length === 1) return "grid-cols-1";
  if (panels.value.length === 2) return "grid-cols-2";
  return "grid-cols-3";
});

function applyFilters(logs: LogEntry[]): LogEntry[] {
  let filtered = logs;
  if (levelFilter.value !== "all") {
    filtered = filtered.filter((log) => log.level === levelFilter.value);
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase();
    filtered = filtered.filter((log) => log.message.toLowerCase().includes(q));
  }
  return filtered;
}

function filteredLogsFor(accountId: string): LogEntry[] {
  return applyFilters(getAccountLogs(accountId));
}

function addPanel(accountId: string, setFocus = true): void {
  if (!accountId) return;
  if (!panels.value.includes(accountId)) {
    if (panels.value.length >= maxPanels) return;
    panels.value = [...panels.value, accountId];
  }
  connectLogStream(accountId);
  if (setFocus) {
    focusedAccountId.value = accountId;
  }
}

function removePanel(accountId: string): void {
  panels.value = panels.value.filter((s) => s !== accountId);
  disconnectLogStream(accountId);
  if (focusedAccountId.value === accountId) {
    focusedAccountId.value = panels.value[0] ?? null;
  }
}

function selectAccount(accountId: string): void {
  addPanel(accountId, true);
}

function clearCurrentLogs(accountId?: string): void {
  const target = accountId || activeAccountId.value;
  if (target) {
    clearLogs(target);
  }
}

function exportLogs(accountId?: string): void {
  const target = accountId || activeAccountId.value;
  if (!target) return;
  const logs = filteredLogsFor(target);
  if (logs.length === 0) return;

  const content = logs
    .map((log) => `[${log.timestamp}] [${log.level}] ${log.message}`)
    .join("\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `wecom-logs-${target}-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

function accountLabel(accountId: string): string {
  const acct = accounts.value.find((a) => a.id === accountId);
  return acct ? acct.name : accountId;
}

onMounted(() => {
  void refreshAccounts();
  timer = setInterval(() => void refreshAccounts(), 5000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
  for (const id of panels.value) {
    disconnectLogStream(id);
  }
});
</script>

<template>
  <div class="h-full flex flex-col animate-fade-in">
    <!-- Header -->
    <div class="p-4 border-b border-wecom-border shrink-0">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-xl font-display font-bold text-wecom-text">运行日志</h2>
          <p class="text-sm text-wecom-muted">实时查看各账号 worker 进程的运行日志。</p>
        </div>
      </div>

      <!-- Filters -->
      <div class="flex items-center gap-4 flex-wrap">
        <!-- Level filter -->
        <select v-model="levelFilter" class="input-field text-sm py-1.5">
          <option value="all">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>

        <!-- Search -->
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索日志内容…"
          class="input-field text-sm py-1.5 flex-1 max-w-xs"
        />

        <!-- Auto-scroll toggle -->
        <label class="flex items-center gap-2 text-sm text-wecom-muted cursor-pointer">
          <input
            v-model="autoScroll"
            type="checkbox"
            class="w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
          />
          自动滚动
        </label>
      </div>
    </div>

    <!-- Account tabs -->
    <div class="flex border-b border-wecom-border shrink-0 overflow-x-auto">
      <button
        v-for="account in accounts"
        :key="account.id"
        class="px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors"
        :class="[
          panels.includes(account.id)
            ? 'text-wecom-primary border-b-2 border-wecom-primary bg-wecom-primary/5'
            : 'text-wecom-muted hover:text-wecom-text hover:bg-wecom-surface',
        ]"
        @click="selectAccount(account.id)"
      >
        {{ account.name }}
        <span
          v-if="getAccountLogs(account.id).length > 0"
          class="ml-2 px-1.5 py-0.5 text-xs rounded-full bg-wecom-surface"
        >
          {{ getAccountLogs(account.id).length }}
        </span>
      </button>

      <div v-if="accounts.length === 0" class="px-4 py-2 text-sm text-wecom-muted">
        暂无账号
      </div>
    </div>

    <!-- Log content -->
    <div class="flex-1 overflow-hidden relative">
      <div v-if="panels.length > 0" class="h-full grid gap-2 p-2" :class="gridColsClass">
        <div
          v-for="accountId in panels"
          :key="accountId"
          class="flex flex-col min-h-0 border border-wecom-border rounded-lg bg-wecom-dark/60 overflow-hidden"
        >
          <div
            class="flex items-center justify-between px-3 py-2 border-b border-wecom-border bg-wecom-dark/80"
            @click="focusedAccountId = accountId"
          >
            <span
              class="px-2 py-1 rounded text-xs"
              :class="[
                focusedAccountId === accountId
                  ? 'bg-wecom-primary/15 text-wecom-primary'
                  : 'bg-wecom-surface text-wecom-text',
              ]"
            >
              {{ accountLabel(accountId) }}
            </span>
            <div class="flex items-center gap-1">
              <button
                class="btn-secondary text-xs px-2 py-1"
                title="清空"
                @click.stop="clearCurrentLogs(accountId)"
              >
                🗑️
              </button>
              <button
                class="btn-secondary text-xs px-2 py-1"
                :disabled="filteredLogsFor(accountId).length === 0"
                title="导出"
                @click.stop="exportLogs(accountId)"
              >
                📥
              </button>
              <button
                class="btn-secondary text-xs px-2 py-1"
                title="关闭"
                @click.stop="removePanel(accountId)"
              >
                ✖️
              </button>
            </div>
          </div>
          <div class="flex-1 min-h-0">
            <LogStream :logs="filteredLogsFor(accountId)" :auto-scroll="autoScroll" />
          </div>
        </div>
      </div>

      <div v-else class="h-full flex flex-col items-center justify-center text-center p-8">
        <div class="text-5xl mb-4">📋</div>
        <h3 class="text-lg font-display font-semibold text-wecom-text mb-2">还没有打开日志面板</h3>
        <p class="text-wecom-muted max-w-md">
          点击上方的账号标签，即可在面板中实时查看该账号 worker 的运行日志。最多可同时打开 3 个账号。
        </p>
      </div>
    </div>
  </div>
</template>
