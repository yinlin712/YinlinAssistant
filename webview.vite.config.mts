import { resolve } from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 文件说明：
// 本文件是 VS Code Webview 前端的独立构建配置。
// 这里采用 Vite + Vue 的轻量构建方式，并保持输出产物固定为 media/webview.js。

export default defineConfig({
  plugins: [vue()],
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
    __VUE_OPTIONS_API__: "true",
    __VUE_PROD_DEVTOOLS__: "false",
  },
  build: {
    outDir: "media",
    emptyOutDir: false,
    cssCodeSplit: false,
    sourcemap: false,
    minify: false,
    lib: {
      entry: resolve(process.cwd(), "webview-src/main.ts"),
      formats: ["iife"],
      name: "CodeAgentWebview",
      fileName: () => "webview.js",
    },
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) => {
          if (assetInfo.name === "style.css") {
            return "webview.css";
          }

          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
