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
  <div class="flex" :class="mine ? 'justify-end' : ''">
    <div
      class="max-w-[min(70%,480px)] whitespace-pre-wrap break-words rounded-[10px] px-3 py-2 text-sm leading-[1.45]"
      :class="
        mine
          ? 'rounded-br-[3px] bg-wecom-accent/30 text-wecom-text'
          : 'rounded-bl-[3px] bg-wecom-surface text-wecom-text'
      "
    >
      <template v-if="msgtype === 'text'">{{ textContent }}</template>

      <a v-else-if="msgtype === 'image' && fileSrc" :href="fileSrc" target="_blank" rel="noopener">
        <img :src="fileSrc" class="block max-w-full rounded-md" alt="图片消息" />
      </a>

      <audio
        v-else-if="msgtype === 'voice' && fileSrc"
        controls
        preload="metadata"
        :src="fileSrc"
        class="mt-1 block h-9 w-[min(280px,100%)]"
      />

      <video
        v-else-if="msgtype === 'video' && fileSrc"
        controls
        preload="metadata"
        playsinline
        :src="fileSrc"
        class="mt-1 block max-h-[360px] max-w-[min(320px,100%)] rounded-md bg-black"
      />

      <a
        v-else-if="fileSrc"
        :href="fileSrc"
        target="_blank"
        rel="noopener"
        class="text-wecom-accent"
      >
        [{{ msgtype }}] 下载
      </a>

      <template v-else>[{{ msgtype }}]</template>

      <div class="mt-1.5 whitespace-normal text-[0.65rem] text-wecom-muted">{{ when }}</div>
    </div>
  </div>
</template>
