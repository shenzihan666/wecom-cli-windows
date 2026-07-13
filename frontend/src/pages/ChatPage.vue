<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { fetchAccounts, fetchConversations, fetchMessages, sendMessage } from "../api";
import MessageBubble from "../components/MessageBubble.vue";
import type { Account, ChatMessage, ConversationsResponse, MessagesResponse } from "../types";

const POLL_MS = 3000;

const route = useRoute();
const router = useRouter();

const accounts = ref<Account[]>([]);
const accountId = ref<string>("");

const currentUserid = ref<string | null>(null);
const stickBottom = ref(true);
const sending = ref(false);
const inputText = ref("");

const convPayload = ref<ConversationsResponse | null>(null);
const msgPayload = ref<MessagesResponse | null>(null);
const syncMeta = ref("同步中…");
const syncErr = ref("");

const msgsEl = ref<HTMLElement | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

const conversations = computed(() => convPayload.value?.conversations ?? []);
const messages = computed(() => msgPayload.value?.messages ?? []);

const chatTitle = computed(() => {
  const p = msgPayload.value;
  if (!p) return "";
  return p.name || p.userid;
});

function snapKey(): string {
  return `wecom_dm_ui_v2_${accountId.value}`;
}

interface Snapshot {
  currentUserid: string | null;
  conversations: ConversationsResponse | null;
  messages: MessagesResponse | null;
}

function loadSnap(): Snapshot | null {
  try {
    return JSON.parse(localStorage.getItem(snapKey()) ?? "null") as Snapshot | null;
  } catch {
    return null;
  }
}

function saveSnap(): void {
  try {
    const snap: Snapshot = {
      currentUserid: currentUserid.value,
      conversations: convPayload.value,
      messages: msgPayload.value,
    };
    localStorage.setItem(snapKey(), JSON.stringify(snap));
  } catch {
    // ignore quota / serialization errors
  }
}

function scrollToBottom(): void {
  void nextTick(() => {
    const el = msgsEl.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function onMsgsScroll(): void {
  const el = msgsEl.value;
  if (!el) return;
  const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
  stickBottom.value = gap < 40;
}

function applyConversations(data: ConversationsResponse | null, fromCache = false): void {
  if (!data) return;
  if (
    !fromCache &&
    convPayload.value &&
    !(data.conversations ?? []).length &&
    (convPayload.value.conversations ?? []).length
  ) {
    syncMeta.value = `${data.last_sync ? `上次同步 ${data.last_sync}` : syncMeta.value} · 刷新中…`;
    return;
  }
  convPayload.value = data;
  if (data.last_sync) {
    syncMeta.value = `上次同步 ${data.last_sync}${fromCache ? " · 本地缓存" : ""}`;
  } else {
    syncMeta.value = fromCache ? "本地缓存" : "等待首次同步…";
  }
  syncErr.value = data.error ?? "";
  saveSnap();
}

function applyMessages(data: MessagesResponse | null, fromCache = false): void {
  if (!data) return;
  const prev = msgPayload.value;
  if (
    !fromCache &&
    prev &&
    data.userid === prev.userid &&
    !(data.messages ?? []).length &&
    (prev.messages ?? []).length
  ) {
    return;
  }
  msgPayload.value = data;
  if ((data.messages ?? []).length && stickBottom.value) scrollToBottom();
  saveSnap();
}

function senderLabel(m: ChatMessage): string {
  const users = msgPayload.value?.users ?? {};
  const uid = m.userid ?? "";
  return users[uid] || uid;
}

function isMine(m: ChatMessage): boolean {
  const self = msgPayload.value?.self_userid || "";
  return m.userid === self;
}

function convClasses(userid: string, hasMessages: boolean): Record<string, boolean> {
  return {
    "bg-wecom-surface shadow-[inset_3px_0_0_theme(colors.wecom.primary)]": userid === currentUserid.value,
    "opacity-60": !hasMessages,
  };
}

async function selectUser(userid: string): Promise<void> {
  currentUserid.value = userid;
  stickBottom.value = true;
  saveSnap();
  const data = await fetchMessages(accountId.value, userid);
  applyMessages(data);
}

async function refresh(): Promise<void> {
  if (!accountId.value) return;
  const data = await fetchConversations(accountId.value);
  applyConversations(data);
  if (currentUserid.value) {
    const msgs = await fetchMessages(accountId.value, currentUserid.value);
    applyMessages(msgs);
  }
}

async function onSend(): Promise<void> {
  const uid = currentUserid.value;
  const content = inputText.value.trim();
  if (!uid || !content) return;

  sending.value = true;
  const prevText = inputText.value;
  inputText.value = "";

  try {
    const res = await sendMessage(accountId.value, uid, content);
    if (!res.ok) {
      inputText.value = prevText;
      syncErr.value = res.error ?? "发送失败";
      return;
    }

    stickBottom.value = true;

    if (res.message) {
      if (!msgPayload.value || msgPayload.value.userid !== uid) {
        const name = conversations.value.find((c) => c.userid === uid)?.name ?? uid;
        msgPayload.value = {
          userid: uid,
          name,
          messages: [],
          last_sync: null,
          self_userid: msgPayload.value?.self_userid ?? "",
          users: {},
        };
      }
      msgPayload.value.messages = [...msgPayload.value.messages, res.message];
      scrollToBottom();
    }

    const cur = convPayload.value;
    if (cur) {
      const hit = cur.conversations.find((c) => c.userid === uid);
      if (hit) {
        hit.last_preview = content;
        hit.last_time = res.message?.send_time ?? hit.last_time;
        hit.has_messages = true;
        cur.conversations = [hit, ...cur.conversations.filter((c) => c.userid !== uid)];
      }
    }
    saveSnap();
    setTimeout(() => void refresh(), 2500);
  } catch (err) {
    inputText.value = prevText;
    syncErr.value = String(err);
  } finally {
    sending.value = false;
  }
}

function resetForAccountSwitch(): void {
  currentUserid.value = null;
  convPayload.value = null;
  msgPayload.value = null;
  syncMeta.value = "同步中…";
  syncErr.value = "";
}

async function bootstrapAccount(): Promise<void> {
  resetForAccountSwitch();
  const snap = loadSnap();
  if (snap) {
    currentUserid.value = snap.currentUserid ?? null;
    if (snap.conversations) applyConversations(snap.conversations, true);
    if (snap.messages && snap.currentUserid && snap.messages.userid === snap.currentUserid) {
      applyMessages(snap.messages, true);
    }
  }
  await refresh();
}

function onAccountChange(): void {
  void router.replace({ query: { ...route.query, account: accountId.value } });
  void bootstrapAccount();
}

watch(
  () => route.query.account,
  (val) => {
    if (typeof val === "string" && val && val !== accountId.value) {
      accountId.value = val;
      void bootstrapAccount();
    }
  },
);

onMounted(async () => {
  const data = await fetchAccounts();
  accounts.value = data.accounts;

  const fromQuery = typeof route.query.account === "string" ? route.query.account : "";
  accountId.value = accounts.value.some((a) => a.id === fromQuery)
    ? fromQuery
    : accounts.value[0]?.id ?? "";

  if (accountId.value && accountId.value !== route.query.account) {
    void router.replace({ query: { ...route.query, account: accountId.value } });
  }

  await bootstrapAccount();
  timer = setInterval(() => void refresh(), POLL_MS);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
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
      <span class="text-xs text-wecom-muted">{{ syncMeta }}</span>
      <span v-if="syncErr" class="text-xs text-red-400">{{ syncErr }}</span>
    </header>

    <div class="grid min-h-0 flex-1 grid-cols-[280px_1fr] overflow-hidden">
      <aside class="flex min-h-0 flex-col overflow-y-auto border-r border-wecom-border bg-wecom-dark">
        <div
          v-for="c in conversations"
          :key="c.userid"
          class="cursor-pointer border-b border-wecom-border px-4 py-3 transition-colors hover:bg-wecom-surface"
          :class="convClasses(c.userid, c.has_messages)"
          @click="selectUser(c.userid)"
        >
          <div class="text-sm font-medium text-wecom-text">{{ c.name }}</div>
          <div class="mt-1 truncate text-xs text-wecom-muted">
            {{ c.last_preview || (c.has_messages ? "" : "暂无近 7 天消息") }}
          </div>
          <div class="mt-0.5 text-[11px] text-wecom-muted">{{ c.last_time }}</div>
        </div>
        <p v-if="!conversations.length" class="p-6 text-center text-sm text-wecom-muted">
          暂无联系人
        </p>
      </aside>

      <section class="flex min-h-0 min-w-0 flex-col overflow-hidden bg-wecom-darker">
        <div class="border-b border-wecom-border bg-wecom-dark/85 px-4 py-3 font-medium text-wecom-text">
          <template v-if="currentUserid">
            {{ chatTitle }}
            <div class="text-xs font-normal text-wecom-muted">{{ msgPayload?.userid }}</div>
          </template>
          <template v-else>选择左侧联系人</template>
        </div>

        <div ref="msgsEl" class="flex flex-1 flex-col gap-2.5 overflow-y-auto p-4" @scroll="onMsgsScroll">
          <p v-if="!currentUserid" class="mt-8 text-center text-sm text-wecom-muted">
            从左侧选择一个私聊对象
          </p>
          <p v-else-if="!messages.length" class="mt-8 text-center text-sm text-wecom-muted">
            近 7 天暂无消息，可直接发送
          </p>
          <MessageBubble
            v-for="(m, i) in messages"
            :key="i"
            :message="m"
            :mine="isMine(m)"
            :sender-label="senderLabel(m)"
          />
        </div>

        <form
          class="flex gap-2 border-t border-wecom-border bg-wecom-dark px-4 py-3"
          @submit.prevent="onSend"
        >
          <input
            v-model="inputText"
            class="input-field flex-1"
            placeholder="输入消息…"
            :disabled="!currentUserid"
            autocomplete="off"
          />
          <button
            type="submit"
            class="btn-primary"
            :disabled="!currentUserid || !inputText.trim() || sending"
          >
            {{ sending ? "发送中…" : "发送" }}
          </button>
        </form>
      </section>
    </div>

    <footer class="shrink-0 border-t border-wecom-border bg-wecom-dark px-4 py-1.5 text-[11px] text-wecom-muted">
      后台约每 5 秒轮询 wecom-cli，页面每 3 秒刷新；仅近约 7 天私聊；发送仅支持文本。非即时推送。
    </footer>
  </div>
</template>
