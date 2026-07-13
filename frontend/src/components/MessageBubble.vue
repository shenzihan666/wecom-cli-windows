<script setup lang="ts">
import { computed } from "vue";
import { mediaUrl } from "../api";
import type { ChatMessage } from "../types";

const props = defineProps<{
  message: ChatMessage;
  mine: boolean;
  senderLabel: string;
}>();

interface MediaPart {
  local_file?: string;
}

const msgtype = computed(() => props.message.msgtype ?? "");

const textContent = computed(() => props.message.text?.content ?? "");

const localFile = computed<string | undefined>(() => {
  const part = props.message[msgtype.value] as MediaPart | undefined;
  return part?.local_file;
});

const fileSrc = computed(() => (localFile.value ? mediaUrl(localFile.value) : ""));

const when = computed(() => {
  const time = props.message.send_time ?? "";
  if (props.mine) return time;
  return props.senderLabel ? `${time} · ${props.senderLabel}` : time;
});
</script>

<template>
  <div class="bubble-row" :class="{ mine }">
    <div class="bubble" :class="mine ? 'mine' : 'theirs'">
      <template v-if="msgtype === 'text'">{{ textContent }}</template>

      <el-image
        v-else-if="msgtype === 'image' && fileSrc"
        :src="fileSrc"
        :preview-src-list="[fileSrc]"
        fit="contain"
        hide-on-click-modal
        preview-teleported
        class="bubble-image"
      />

      <audio
        v-else-if="msgtype === 'voice' && fileSrc"
        controls
        preload="metadata"
        :src="fileSrc"
      />

      <video
        v-else-if="msgtype === 'video' && fileSrc"
        controls
        preload="metadata"
        playsinline
        :src="fileSrc"
      />

      <a v-else-if="fileSrc" :href="fileSrc" target="_blank" rel="noopener">
        [{{ msgtype }}] 下载
      </a>

      <template v-else>[{{ msgtype }}]</template>

      <div class="when">{{ when }}</div>
    </div>
  </div>
</template>

<style scoped>
.bubble-row {
  display: flex;
}

.bubble-row.mine {
  justify-content: flex-end;
}

.bubble {
  max-width: min(70%, 480px);
  padding: 0.55rem 0.75rem;
  border-radius: 10px;
  font-size: 0.9rem;
  line-height: 1.45;
  word-break: break-word;
  white-space: pre-wrap;
}

.bubble.mine {
  background: var(--mine);
  border-bottom-right-radius: 3px;
}

.bubble.theirs {
  background: var(--theirs);
  border-bottom-left-radius: 3px;
}

.bubble .when {
  font-size: 0.65rem;
  color: var(--muted);
  margin-top: 0.35rem;
  white-space: normal;
}

.bubble-image {
  max-width: 100%;
  border-radius: 6px;
  display: block;
}

.bubble audio {
  display: block;
  width: min(280px, 100%);
  height: 36px;
  margin-top: 0.15rem;
}

.bubble video {
  display: block;
  max-width: min(320px, 100%);
  max-height: 360px;
  border-radius: 6px;
  margin-top: 0.15rem;
  background: #000;
}

.bubble a {
  color: #9ec1ff;
}
</style>
