<script setup lang="ts">
import { Promotion } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { fetchConversations, fetchMessages, sendMessage } from "./api";
import MessageBubble from "./components/MessageBubble.vue";
import type { ChatMessage, ConversationsResponse, MessagesResponse } from "./types";

const LS_KEY = "wecom_dm_ui_v1";
const POLL_MS = 3000;

const selfUserid = ref("");
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

interface Snapshot {
  selfUserid: string;
  currentUserid: string | null;
  conversations: ConversationsResponse | null;
  messages: MessagesResponse | null;
}

function loadSnap(): Snapshot | null {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) ?? "null") as Snapshot | null;
  } catch {
    return null;
  }
}

function saveSnap(): void {
  try {
    const snap: Snapshot = {
      selfUserid: selfUserid.value,
      currentUserid: currentUserid.value,
      conversations: convPayload.value,
      messages: msgPayload.value,
    };
    localStorage.setItem(LS_KEY, JSON.stringify(snap));
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
  // Don't wipe a good list with an empty transient response.
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
  selfUserid.value = data.self_userid || selfUserid.value;
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
  const self = msgPayload.value?.self_userid || selfUserid.value;
  return m.userid === self;
}

function convClasses(userid: string, hasMessages: boolean): Record<string, boolean> {
  return {
    active: userid === currentUserid.value,
    empty: !hasMessages,
  };
}

async function selectUser(userid: string): Promise<void> {
  currentUserid.value = userid;
  stickBottom.value = true;
  saveSnap();
  const data = await fetchMessages(userid);
  applyMessages(data);
}

async function refresh(): Promise<void> {
  const data = await fetchConversations();
  applyConversations(data);
  if (currentUserid.value) {
    const msgs = await fetchMessages(currentUserid.value);
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
    const res = await sendMessage(uid, content);
    if (!res.ok) {
      inputText.value = prevText;
      ElMessage.error(res.error ?? "发送失败");
      return;
    }

    stickBottom.value = true;

    // Paint from the send response to avoid racing the poll's API lag.
    if (res.message) {
      if (!msgPayload.value || msgPayload.value.userid !== uid) {
        const name = conversations.value.find((c) => c.userid === uid)?.name ?? uid;
        msgPayload.value = {
          userid: uid,
          name,
          messages: [],
          last_sync: null,
          self_userid: selfUserid.value,
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
    ElMessage.error(String(err));
  } finally {
    sending.value = false;
  }
}

onMounted(() => {
  const snap = loadSnap();
  if (snap) {
    selfUserid.value = snap.selfUserid || "";
    currentUserid.value = snap.currentUserid ?? null;
    if (snap.conversations) applyConversations(snap.conversations, true);
    if (snap.messages && snap.currentUserid && snap.messages.userid === snap.currentUserid) {
      applyMessages(snap.messages, true);
    }
  }
  void refresh();
  timer = setInterval(() => void refresh(), POLL_MS);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="layout">
    <header class="app-header">
      <h1>WeCom 私聊</h1>
      <span class="meta">{{ syncMeta }}</span>
      <span v-if="syncErr" class="err">{{ syncErr }}</span>
    </header>

    <div class="app">
      <aside class="sidebar">
        <div
          v-for="c in conversations"
          :key="c.userid"
          class="conv"
          :class="convClasses(c.userid, c.has_messages)"
          @click="selectUser(c.userid)"
        >
          <div class="name">{{ c.name }}</div>
          <div class="preview">
            {{ c.last_preview || (c.has_messages ? "" : "暂无近 7 天消息") }}
          </div>
          <div class="time">{{ c.last_time }}</div>
        </div>
        <el-empty v-if="!conversations.length" description="暂无联系人" :image-size="64" />
      </aside>

      <section class="chat">
        <div class="chat-head">
          <template v-if="currentUserid">
            {{ chatTitle }}
            <div class="sub">{{ msgPayload?.userid }}</div>
          </template>
          <template v-else>选择左侧联系人</template>
        </div>

        <div ref="msgsEl" class="msgs" @scroll="onMsgsScroll">
          <el-empty v-if="!currentUserid" description="从左侧选择一个私聊对象" :image-size="80" />
          <el-empty
            v-else-if="!messages.length"
            description="近 7 天暂无消息，可直接发送"
            :image-size="80"
          />
          <MessageBubble
            v-for="(m, i) in messages"
            :key="i"
            :message="m"
            :mine="isMine(m)"
            :sender-label="senderLabel(m)"
          />
        </div>

        <form class="composer" @submit.prevent="onSend">
          <el-input
            v-model="inputText"
            placeholder="输入消息…"
            :disabled="!currentUserid"
            autocomplete="off"
            @keyup.enter="onSend"
          />
          <el-button
            type="primary"
            native-type="submit"
            :disabled="!currentUserid || !inputText.trim()"
            :loading="sending"
            :icon="Promotion"
          >
            发送
          </el-button>
        </form>
      </section>
    </div>

    <footer class="app-footer">
      后台约每 5 秒轮询 wecom-cli，页面每 3 秒刷新；仅近约 7 天私聊；发送仅支持文本。非即时推送。
    </footer>
  </div>
</template>

<style scoped>
.layout {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}

.app-header h1 {
  font-size: 1rem;
  margin: 0;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.app-header .meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.app-header .err {
  color: var(--danger);
  font-size: 0.75rem;
}

.app {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr;
  min-height: 0;
  overflow: hidden;
}

.sidebar {
  border-right: 1px solid var(--border);
  background: var(--panel);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.conv {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.12s;
}

.conv:hover {
  background: var(--panel2);
}

.conv.active {
  background: var(--panel2);
  box-shadow: inset 3px 0 0 var(--accent);
}

.conv .name {
  font-size: 0.9rem;
  font-weight: 500;
}

.conv .preview {
  font-size: 0.75rem;
  color: var(--muted);
  margin-top: 0.25rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.conv .time {
  font-size: 0.65rem;
  color: var(--muted);
  margin-top: 0.2rem;
}

.conv.empty .name {
  color: var(--muted);
}

.chat {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: radial-gradient(ellipse at top left, #1a2838 0%, transparent 50%), var(--bg);
}

.chat-head {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  font-weight: 500;
  background: rgba(26, 34, 44, 0.85);
}

.chat-head .sub {
  font-size: 0.7rem;
  color: var(--muted);
  font-weight: 400;
}

.msgs {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.composer {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--panel);
}

.app-footer {
  flex-shrink: 0;
  padding: 0.4rem 1rem;
  font-size: 0.65rem;
  color: var(--muted);
  border-top: 1px solid var(--border);
  background: var(--panel);
}

@media (max-width: 720px) {
  .app {
    grid-template-columns: 1fr;
  }

  .sidebar {
    max-height: 40vh;
  }
}
</style>
