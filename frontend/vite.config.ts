import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite-plus";

// The FastAPI backend serves /api/* and /media/* on 127.0.0.1:8765.
// During `vp dev` we proxy those paths so the SPA can call them same-origin.
// Change this if your backend runs elsewhere.
const BACKEND = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/media": { target: BACKEND, changeOrigin: true },
    },
  },
  fmt: {},
  lint: {
    jsPlugins: [{ name: "vite-plus", specifier: "vite-plus/oxlint-plugin" }],
    rules: { "vite-plus/prefer-vite-plus-imports": "error" },
    options: { typeAware: true, typeCheck: true },
  },
});
