<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const navItems = [
  { name: "accounts", path: "/accounts", icon: "🧑‍💼", label: "客服管理" },
  { name: "chat", path: "/chat", icon: "💬", label: "聊天记录" },
  { name: "settings", path: "/settings", icon: "⚙️", label: "设置" },
] as const;

function isActive(item: { name: string }): boolean {
  return route.name === item.name;
}

const isCollapsed = ref(false);

function toggleCollapse(): void {
  isCollapsed.value = !isCollapsed.value;
}

const sidebarWidthClass = computed(() => (isCollapsed.value ? "w-14" : "w-56"));
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-wecom-darker">
    <header
      class="flex h-12 shrink-0 items-center border-b border-wecom-border bg-wecom-dark px-4"
    >
      <h1 class="font-display text-sm font-semibold text-wecom-text">WeCom 私聊同步</h1>
    </header>

    <div class="flex flex-1 overflow-hidden">
      <aside
        class="relative flex shrink-0 flex-col border-r border-wecom-border bg-wecom-dark transition-[width] duration-200"
        :class="sidebarWidthClass"
      >
        <button
          class="absolute -right-3 top-4 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-wecom-border bg-wecom-surface text-wecom-muted shadow-sm transition-all duration-200 hover:bg-wecom-primary/20 hover:text-wecom-text"
          :title="isCollapsed ? '展开侧边栏' : '收起侧边栏'"
          @click="toggleCollapse"
        >
          <span class="text-xs transition-transform duration-200" :class="isCollapsed ? 'rotate-180' : ''"
            >‹</span
          >
        </button>

        <nav class="flex-1 space-y-1 overflow-hidden p-3">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="flex items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-all duration-200"
            :class="[
              isActive(item)
                ? 'bg-wecom-primary/20 text-wecom-primary'
                : 'text-wecom-muted hover:bg-wecom-surface hover:text-wecom-text',
              isCollapsed ? 'justify-center' : '',
            ]"
            :title="isCollapsed ? item.label : ''"
          >
            <span class="shrink-0">{{ item.icon }}</span>
            <span v-show="!isCollapsed" class="overflow-hidden font-medium">{{ item.label }}</span>
          </router-link>
        </nav>
      </aside>

      <main class="flex-1 overflow-hidden">
        <router-view />
      </main>
    </div>
  </div>
</template>
