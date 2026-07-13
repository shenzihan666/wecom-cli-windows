<script setup lang="ts">
import { onMounted, ref } from "vue";
import { fetchSettings, updateSettings } from "../api";

const pollSec = ref<number>(5);
const loading = ref(false);
const saving = ref(false);
const errorMsg = ref("");
const savedMsg = ref("");

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await fetchSettings();
    pollSec.value = data.poll_sec;
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
  saving.value = true;
  try {
    const data = await updateSettings(pollSec.value);
    pollSec.value = data.poll_sec;
    savedMsg.value = "已保存，正在运行的账号会自动按新间隔重启轮询";
  } catch (err) {
    errorMsg.value = String(err);
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="h-full overflow-auto p-6">
    <div class="mx-auto max-w-2xl space-y-6">
      <div>
        <h2 class="font-display text-2xl font-bold text-wecom-text">设置</h2>
        <p class="mt-1 text-sm text-wecom-muted">配置同步相关的全局参数。</p>
      </div>

      <div class="card space-y-4 p-5">
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

        <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>
        <p v-if="savedMsg" class="text-sm text-emerald-400">{{ savedMsg }}</p>

        <div>
          <button class="btn-primary" :disabled="loading || saving" @click="onSave">
            {{ saving ? "保存中…" : "保存" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
