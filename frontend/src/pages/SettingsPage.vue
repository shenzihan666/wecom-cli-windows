<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchSettings, updateSettings } from "../api";

const pollSec = ref<number>(5);
const aiEnabled = ref(false);
const aiServerUrl = ref("http://localhost:8080");
const aiTimeoutSec = ref(15);
const aiSystemPrompt = ref("");
const aiReplyMaxLength = ref(50);
const aiHistoryLimit = ref(30);

const loading = ref(false);
const saving = ref(false);
const errorMsg = ref("");
const savedMsg = ref("");

async function loadSettings(): Promise<void> {
  loading.value = true;
  try {
    const data = await fetchSettings();
    pollSec.value = data.poll_sec;
    aiEnabled.value = data.ai_enabled;
    aiServerUrl.value = data.ai_server_url;
    aiTimeoutSec.value = data.ai_timeout_sec;
    aiSystemPrompt.value = data.ai_system_prompt;
    aiReplyMaxLength.value = data.ai_reply_max_length;
    aiHistoryLimit.value = data.ai_history_limit;
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    loading.value = false;
  }
}

async function onSave(): Promise<void> {
  errorMsg.value = "";
  savedMsg.value = "";
  if (!Number.isFinite(pollSec.value) || pollSec.value <= 0) {
    errorMsg.value = "轮询间隔必须为正数";
    return;
  }
  if (!Number.isFinite(aiTimeoutSec.value) || aiTimeoutSec.value <= 0) {
    errorMsg.value = "AI 超时必须为正数";
    return;
  }
  if (!Number.isFinite(aiReplyMaxLength.value) || aiReplyMaxLength.value <= 0) {
    errorMsg.value = "回复最大长度必须为正数";
    return;
  }
  if (!Number.isFinite(aiHistoryLimit.value) || aiHistoryLimit.value <= 0) {
    errorMsg.value = "历史条数必须为正数";
    return;
  }
  saving.value = true;
  try {
    const data = await updateSettings({
      poll_sec: pollSec.value,
      ai_enabled: aiEnabled.value,
      ai_server_url: aiServerUrl.value,
      ai_timeout_sec: aiTimeoutSec.value,
      ai_system_prompt: aiSystemPrompt.value,
      ai_reply_max_length: aiReplyMaxLength.value,
      ai_history_limit: aiHistoryLimit.value,
    });
    pollSec.value = data.poll_sec;
    aiEnabled.value = data.ai_enabled;
    aiServerUrl.value = data.ai_server_url;
    aiTimeoutSec.value = data.ai_timeout_sec;
    aiSystemPrompt.value = data.ai_system_prompt;
    aiReplyMaxLength.value = data.ai_reply_max_length;
    aiHistoryLimit.value = data.ai_history_limit;
    savedMsg.value = "已保存。AI 配置立即生效；若修改了轮询间隔，运行中的账号会自动重启。";
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await loadSettings();
});
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mx-auto max-w-2xl space-y-6">
      <div>
        <h2 class="font-display text-2xl font-bold text-wecom-text">设置</h2>
        <p class="mt-1 text-sm text-wecom-muted">配置同步与 AI 自动回复相关参数。</p>
      </div>

      <div class="card space-y-4 p-5">
        <h3 class="text-base font-semibold text-wecom-text">同步</h3>
        <div class="space-y-1">
          <label class="text-sm font-medium text-wecom-text">轮询间隔 poll_sec（秒）</label>
          <p class="text-xs text-wecom-muted">
            后端每隔多少秒轮询一次 wecom-cli 同步私聊消息。修改后会自动重启当前运行中的账号。
          </p>
          <input
            v-model.number="pollSec"
            type="number"
            min="1"
            step="1"
            class="input-field w-40"
            :disabled="loading"
          />
        </div>
      </div>

      <div class="card space-y-4 p-5">
        <h3 class="text-base font-semibold text-wecom-text">AI 自动回复</h3>
        <p class="text-xs text-wecom-muted">
          开启后，轮询同步发现未回复的文本消息时，会调用 AI 生成回复并直接发送。
        </p>

        <label class="flex items-center gap-2 text-sm text-wecom-text">
          <input v-model="aiEnabled" type="checkbox" class="rounded border-wecom-border" :disabled="loading" />
          启用 AI 自动回复
        </label>

        <div class="space-y-1">
          <label class="text-sm font-medium text-wecom-text">AI 服务地址</label>
          <input
            v-model="aiServerUrl"
            type="text"
            class="input-field w-full"
            placeholder="http://localhost:8080"
            :disabled="loading"
          />
        </div>

        <div class="flex flex-wrap gap-4">
          <div class="space-y-1">
            <label class="text-sm font-medium text-wecom-text">超时（秒）</label>
            <input
              v-model.number="aiTimeoutSec"
              type="number"
              min="1"
              step="1"
              class="input-field w-28"
              :disabled="loading"
            />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium text-wecom-text">回复最大长度</label>
            <input
              v-model.number="aiReplyMaxLength"
              type="number"
              min="1"
              step="1"
              class="input-field w-28"
              :disabled="loading"
            />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium text-wecom-text">历史消息条数</label>
            <input
              v-model.number="aiHistoryLimit"
              type="number"
              min="1"
              step="1"
              class="input-field w-28"
              :disabled="loading"
            />
          </div>
        </div>

        <div class="space-y-1">
          <label class="text-sm font-medium text-wecom-text">系统提示词</label>
          <textarea
            v-model="aiSystemPrompt"
            rows="5"
            class="input-field w-full resize-y"
            placeholder="例如：你是企业微信客服，语气礼貌简洁……"
            :disabled="loading"
          />
        </div>
      </div>

      <div class="card space-y-4 p-5">
        <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>
        <p v-if="savedMsg" class="text-sm text-emerald-400">{{ savedMsg }}</p>
        <button class="btn-primary" :disabled="loading || saving" @click="onSave">
          {{ saving ? "保存中…" : "保存设置" }}
        </button>
      </div>
    </div>
  </div>
</template>
