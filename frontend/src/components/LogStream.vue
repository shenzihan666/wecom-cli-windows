<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import type { LogEntry } from "../stores/logs";

const props = defineProps<{
  logs: LogEntry[];
  autoScroll?: boolean;
}>();

const containerRef = ref<HTMLElement | null>(null);

// Level -> text color.
const levelColors: Record<string, string> = {
  DEBUG: "text-gray-400",
  INFO: "text-blue-400",
  WARNING: "text-yellow-400",
  ERROR: "text-red-400",
};

// Level -> subtle background tint.
const levelBgs: Record<string, string> = {
  DEBUG: "bg-gray-500/10",
  INFO: "bg-blue-500/10",
  WARNING: "bg-yellow-500/10",
  ERROR: "bg-red-500/10",
};

function formatTime(timestamp: string): string {
  // The backend timestamp is either an ISO string or "YYYY-MM-DD HH:MM:SS".
  // Show only the time portion for compactness.
  try {
    const date = new Date(timestamp.replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return timestamp;
    return date.toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return timestamp;
  }
}

// rAF-coalesced auto-scroll. Coalesces a burst of log lines into one scroll
// per animation frame so we never force layout more than ~60x/s.
let rafHandle: number | null = null;
let pendingScroll = false;

function scheduleAutoScroll(): void {
  if (!props.autoScroll) return;
  pendingScroll = true;
  if (rafHandle !== null) return;
  rafHandle = requestAnimationFrame(() => {
    rafHandle = null;
    if (!pendingScroll) return;
    pendingScroll = false;
    const el = containerRef.value;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  });
}

// Watch the last entry's id rather than `logs.length`: once the buffer caps at
// maxLogs the store splices one old entry per new one, so length stops changing
// and a length-only watch would silently stop firing.
watch(
  () => props.logs[props.logs.length - 1]?.id,
  (newId: string | undefined, oldId: string | undefined) => {
    if (newId !== oldId) scheduleAutoScroll();
  },
);

onMounted(() => {
  if (props.autoScroll && containerRef.value) {
    scheduleAutoScroll();
  }
});

onBeforeUnmount(() => {
  if (rafHandle !== null) {
    cancelAnimationFrame(rafHandle);
    rafHandle = null;
  }
});
</script>

<template>
  <div
    ref="containerRef"
    class="h-full overflow-y-auto bg-wecom-darker font-mono text-sm relative"
  >
    <!-- Empty state -->
    <div
      v-if="logs.length === 0"
      class="h-full flex flex-col items-center justify-center text-center p-8"
    >
      <div class="text-4xl mb-3 opacity-50">📝</div>
      <p class="text-wecom-muted">暂无日志</p>
      <p class="text-wecom-muted/50 text-xs mt-1">启动账号后，运行日志会在这里实时显示</p>
    </div>

    <!-- Log entries -->
    <div v-else class="p-2 space-y-0.5">
      <div
        v-for="log in logs"
        :key="log.id"
        class="flex items-start gap-2 py-1 px-2 rounded hover:bg-wecom-surface/50 transition-colors log-entry-enter-active"
        :class="levelBgs[log.level]"
      >
        <!-- Timestamp -->
        <span class="text-wecom-muted/60 shrink-0 w-20">
          {{ formatTime(log.timestamp) }}
        </span>

        <!-- Level badge -->
        <span class="shrink-0 w-16 text-xs font-semibold" :class="levelColors[log.level]">
          [{{ log.level }}]
        </span>

        <!-- Message -->
        <span
          class="flex-1 break-all"
          :class="log.level === 'ERROR' ? 'text-red-300' : 'text-wecom-text/90'"
        >
          {{ log.message }}
        </span>
      </div>
    </div>

    <!-- Scroll anchor -->
    <div class="h-1"></div>
  </div>
</template>

<style scoped>
/* Short, lightweight enter animation. Kept deliberately tiny so bursts of
 * entries don't pressure the compositor with one layer per row. */
:deep(.log-entry-enter-active) {
  animation: slideIn 0.06s ease-out;
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
