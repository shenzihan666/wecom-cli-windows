<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  addBlacklist,
  fetchAccounts,
  fetchBlacklist,
  fetchConversations,
  removeBlacklist,
} from "../api";
import type { Account, BlacklistItem, ConversationsResponse } from "../types";

const route = useRoute();
const router = useRouter();

const accounts = ref<Account[]>([]);
const accountId = ref<string>("");

const convPayload = ref<ConversationsResponse | null>(null);
const blacklist = ref<BlacklistItem[]>([]);
const searchQuery = ref("");

const loading = ref(false);
const errorMsg = ref("");
const toggling = ref<Record<string, boolean>>({});

const conversations = computed(() => convPayload.value?.conversations ?? []);
const blacklistUserids = computed(() => new Set(blacklist.value.map((i) => i.userid)));
const filteredConversations = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return conversations.value;
  return conversations.value.filter(
    (c) => c.name.toLowerCase().includes(q) || c.userid.toLowerCase().includes(q),
  );
});

function isBlacklisted(userid: string): boolean {
  return blacklistUserids.value.has(userid);
}

async function loadAccounts(): Promise<void> {
  try {
    const data = await fetchAccounts();
    accounts.value = data.accounts;

    const fromQuery = typeof route.query.account === "string" ? route.query.account : "";
    accountId.value = accounts.value.some((a) => a.id === fromQuery)
      ? fromQuery
      : accounts.value[0]?.id ?? "";

    if (accountId.value && accountId.value !== route.query.account) {
      void router.replace({ query: { ...route.query, account: accountId.value } });
    }
  } catch (err) {
    errorMsg.value = String(err);
  }
}

async function loadConversations(): Promise<void> {
  if (!accountId.value) {
    convPayload.value = null;
    return;
  }
  try {
    convPayload.value = await fetchConversations(accountId.value);
  } catch (err) {
    errorMsg.value = String(err);
  }
}

async function loadBlacklist(): Promise<void> {
  if (!accountId.value) {
    blacklist.value = [];
    return;
  }
  try {
    const data = await fetchBlacklist(accountId.value);
    blacklist.value = data.items;
  } catch (err) {
    errorMsg.value = String(err);
  }
}

async function loadAll(): Promise<void> {
  if (!accountId.value) return;
  loading.value = true;
  errorMsg.value = "";
  try {
    await Promise.all([loadConversations(), loadBlacklist()]);
  } finally {
    loading.value = false;
  }
}

function onAccountChange(): void {
  void router.replace({ query: { ...route.query, account: accountId.value } });
  void loadAll();
}

async function toggleBlacklist(userid: string, name: string): Promise<void> {
  if (!accountId.value || toggling.value[userid]) return;
  toggling.value[userid] = true;
  errorMsg.value = "";
  try {
    if (isBlacklisted(userid)) {
      await removeBlacklist(accountId.value, userid);
    } else {
      await addBlacklist(accountId.value, { userid, name, reason: "" });
    }
    await loadBlacklist();
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    toggling.value[userid] = false;
  }
}

watch(
  () => route.query.account,
  (val) => {
    if (typeof val === "string" && val && val !== accountId.value) {
      accountId.value = val;
      void loadAll();
    }
  },
);

onMounted(async () => {
  await loadAccounts();
  await loadAll();
});
</script>

<template>
  <div class="flex h-full flex-col">
    <header
      class="flex flex-wrap items-center gap-3 border-b border-wecom-border bg-wecom-dark px-4 py-2.5"
    >
      <select
        v-model="accountId"
        class="input-field max-w-[220px] py-1.5 text-sm"
        @change="onAccountChange"
      >
        <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.name }}</option>
      </select>
      <input
        v-model="searchQuery"
        type="text"
        class="input-field max-w-[240px] py-1.5 text-sm"
        placeholder="按名字或 userid 搜索…"
        autocomplete="off"
      />
      <span v-if="loading" class="text-xs text-wecom-muted">加载中…</span>
      <span v-if="errorMsg" class="text-xs text-red-400">{{ errorMsg }}</span>
    </header>

    <div class="flex-1 overflow-y-auto bg-wecom-darker">
      <p v-if="!accounts.length" class="p-6 text-center text-sm text-wecom-muted">
        请先在「客服管理」中添加账号。
      </p>
      <p v-else-if="!conversations.length" class="p-6 text-center text-sm text-wecom-muted">
        暂无联系人，请先启动账号同步。
      </p>
      <p v-else-if="!filteredConversations.length" class="p-6 text-center text-sm text-wecom-muted">
        没有匹配「{{ searchQuery }}」的联系人。
      </p>

      <ul v-else class="divide-y divide-wecom-border/40">
        <li
          v-for="c in filteredConversations"
          :key="c.userid"
          class="flex items-center justify-between gap-3 px-4 py-3 transition-colors"
          :class="
            isBlacklisted(c.userid)
              ? 'bg-red-500/10 shadow-[inset_3px_0_0_theme(colors.red.500)]'
              : 'hover:bg-wecom-surface'
          "
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-medium text-wecom-text">{{ c.name }}</span>
              <span
                v-if="isBlacklisted(c.userid)"
                class="shrink-0 rounded bg-red-500/20 px-1.5 py-0.5 text-[11px] font-medium text-red-400"
              >
                已拉黑
              </span>
            </div>
            <div class="mt-0.5 truncate text-xs text-wecom-muted">{{ c.userid }}</div>
          </div>

          <button
            v-if="isBlacklisted(c.userid)"
            class="btn-danger shrink-0 px-3 py-1.5 text-sm"
            :disabled="toggling[c.userid]"
            @click="toggleBlacklist(c.userid, c.name)"
          >
            {{ toggling[c.userid] ? "…" : "移除" }}
          </button>
          <button
            v-else
            class="btn-primary shrink-0 px-3 py-1.5 text-sm"
            :disabled="toggling[c.userid]"
            @click="toggleBlacklist(c.userid, c.name)"
          >
            {{ toggling[c.userid] ? "…" : "加入黑名单" }}
          </button>
        </li>
      </ul>
    </div>

    <footer class="shrink-0 border-t border-wecom-border bg-wecom-dark px-4 py-1.5 text-[11px] text-wecom-muted">
      黑名单内的联系人不会触发 AI 自动回复，按账号隔离。
    </footer>
  </div>
</template>
