import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/accounts" },
    {
      path: "/accounts",
      name: "accounts",
      component: () => import("./pages/AccountsPage.vue"),
    },
    {
      path: "/chat",
      name: "chat",
      component: () => import("./pages/ChatPage.vue"),
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("./pages/SettingsPage.vue"),
    },
    {
      path: "/logs",
      name: "logs",
      component: () => import("./pages/LogsPage.vue"),
    },
  ],
});

export default router;
