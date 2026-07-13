<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { createAccount, deleteAccount, fetchAccounts, pauseAccount, startAccount } from "../api";
import type { Account } from "../types";

const REFRESH_MS = 4000;

const accounts = ref<Account[]>([]);
const loading = ref(false);
const errorMsg = ref("");
const busyIds = ref<Set<string>>(new Set());

const showAddForm = ref(false);
const formName = ref("");
const formConfigDir = ref("");
const formSelfUserid = ref("");
const formError = ref("");
const submitting = ref(false);

let timer: ReturnType<typeof setInterval> | undefined;

function stateLabel(state: Account["state"]): string {
  if (state === "running") return "运行中";
  if (state === "paused") return "已暂停";
  return "已停止";
}

function stateDotClass(state: Account["state"]): string {
  if (state === "running") return "bg-emerald-500 status-pulse";
  if (state === "paused") return "bg-amber-500";
  return "bg-wecom-muted";
}

async function refresh(): Promise<void> {
  try {
    const data = await fetchAccounts();
    accounts.value = data.accounts;
    errorMsg.value = "";
  } catch (err) {
    errorMsg.value = String(err);
  }
}

async function toggleForm(): Promise<void> {
  showAddForm.value = !showAddForm.value;
  formError.value = "";
  if (showAddForm.value) {
    formName.value = "";
    formConfigDir.value = "";
    formSelfUserid.value = "";
  }
}

async function onSubmitAdd(): Promise<void> {
  submitting.value = true;
  formError.value = "";
  try {
    await createAccount({
      name: formName.value.trim() || undefined,
      config_dir: formConfigDir.value.trim() || null,
      self_userid: formSelfUserid.value.trim() || undefined,
    });
    showAddForm.value = false;
    await refresh();
  } catch (err) {
    formError.value = String(err);
  } finally {
    submitting.value = false;
  }
}

async function onDelete(account: Account): Promise<void> {
  if (!window.confirm(`确定删除账号「${account.name}」吗？`)) return;
  busyIds.value.add(account.id);
  try {
    await deleteAccount(account.id);
    await refresh();
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    busyIds.value.delete(account.id);
  }
}

async function onToggleRun(account: Account): Promise<void> {
  busyIds.value.add(account.id);
  try {
    if (account.state === "running") {
      await pauseAccount(account.id);
    } else {
      await startAccount(account.id);
    }
    await refresh();
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    busyIds.value.delete(account.id);
  }
}

onMounted(() => {
  loading.value = true;
  void refresh().finally(() => {
    loading.value = false;
  });
  timer = setInterval(() => void refresh(), REFRESH_MS);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mx-auto max-w-4xl space-y-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="font-display text-2xl font-bold text-wecom-text">客服管理</h2>
          <p class="mt-1 text-sm text-wecom-muted">
            管理已注册的 wecom-cli 账号，控制轮询同步的启动与暂停。
          </p>
        </div>
        <button class="btn-primary" @click="toggleForm">
          {{ showAddForm ? "取消" : "+ 添加账号" }}
        </button>
      </div>

      <div v-if="showAddForm" class="card animate-fade-in space-y-3 p-5">
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted">账号名称（可选）</label>
            <input
              v-model="formName"
              class="input-field w-full"
              placeholder="留空则同步后自动填入企微姓名"
            />
          </div>
          <div class="space-y-1">
            <label class="text-xs text-wecom-muted">self_userid（可选覆盖）</label>
            <input v-model="formSelfUserid" class="input-field w-full" placeholder="留空自动检测" />
          </div>
          <div class="space-y-1 sm:col-span-2">
            <label class="text-xs text-wecom-muted">wecom-cli config_dir 路径</label>
            <input
              v-model="formConfigDir"
              class="input-field w-full"
              placeholder="例如：C:\Users\me\.wecom-cli\profile1"
            />
          </div>
        </div>
        <p v-if="formError" class="text-sm text-red-400">{{ formError }}</p>
        <div class="flex justify-end gap-2">
          <button class="btn-secondary" @click="toggleForm">取消</button>
          <button class="btn-primary" :disabled="submitting" @click="onSubmitAdd">
            {{ submitting ? "保存中…" : "保存" }}
          </button>
        </div>
      </div>

      <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>

      <div v-if="loading" class="text-sm text-wecom-muted">加载中…</div>
      <div v-else-if="!accounts.length" class="card p-8 text-center text-sm text-wecom-muted">
        暂无账号，点击右上角「添加账号」注册一个 wecom-cli config_dir。
      </div>

      <div v-else class="grid gap-4 sm:grid-cols-2">
        <div v-for="account in accounts" :key="account.id" class="card card-hover p-5">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h3 class="truncate font-display text-base font-semibold text-wecom-text">
                {{ account.name }}
              </h3>
              <p class="mt-0.5 truncate text-xs text-wecom-muted" :title="account.config_dir ?? ''">
                {{ account.config_dir || "（未设置 config_dir）" }}
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-1.5 text-xs text-wecom-muted">
              <span class="h-2 w-2 rounded-full" :class="stateDotClass(account.state)"></span>
              {{ stateLabel(account.state) }}
            </div>
          </div>

          <dl class="mt-3 space-y-1 text-xs text-wecom-muted">
            <div class="flex justify-between gap-2">
              <dt>self_userid</dt>
              <dd class="truncate text-wecom-text">{{ account.self_userid || "—" }}</dd>
            </div>
            <div class="flex justify-between gap-2">
              <dt>上次同步</dt>
              <dd class="truncate text-wecom-text">{{ account.last_sync || "尚未同步" }}</dd>
            </div>
          </dl>
          <p v-if="account.error" class="mt-2 text-xs text-red-400">{{ account.error }}</p>

          <div class="mt-4 flex gap-2">
            <button
              class="btn-secondary flex-1"
              :disabled="busyIds.has(account.id)"
              @click="onToggleRun(account)"
            >
              {{ account.state === "running" ? "暂停" : "启动" }}
            </button>
            <router-link
              :to="{ path: '/chat', query: { account: account.id } }"
              class="btn-secondary flex-1 text-center"
            >
              查看聊天
            </router-link>
            <button
              class="btn-danger"
              :disabled="busyIds.has(account.id)"
              title="删除账号"
              @click="onDelete(account)"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
