import { createApp } from "vue";

// 文件说明：
// 本文件是 Vue Webview 的入口，负责挂载根组件。

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Webview root element was not found.");
}
const mountTarget: HTMLElement = rootElement;
mountTarget.innerHTML = `
  <section style="
    padding: 12px;
    color: var(--vscode-descriptionForeground, #8a8a8a);
    font-family: var(--vscode-font-family, 'Segoe UI', sans-serif);
  ">
    Code Agent 正在初始化...
  </section>
`;

window.addEventListener("error", (event) => {
  renderBootError(`Webview 启动失败：${event.message}`, event.error);
});

window.addEventListener("unhandledrejection", (event) => {
  renderBootError("Webview 启动失败：存在未处理的异步异常。", event.reason);
});

try {
  void bootstrap();
} catch (error) {
  renderBootError("Webview 初始化失败。", error);
}

/**
 * 动态加载根组件，让启动期错误能够被统一兜底显示。
 */
async function bootstrap(): Promise<void> {
  try {
    const module = await import("./App.vue");
    const App = module.default;
    const app = createApp(App);
    app.config.errorHandler = (error, _instance, info) => {
      renderBootError(`Webview 运行错误：${info}`, error);
    };
    app.mount(mountTarget);
  } catch (error) {
    renderBootError("Webview 初始化失败。", error);
  }
}

/**
 * 将启动期错误以可见方式输出到侧边栏，便于定位问题。
 */
function renderBootError(summary: string, error: unknown): void {
  const detail = error instanceof Error
    ? `${error.name}: ${error.message}\n${error.stack ?? ""}`
    : String(error ?? "未知错误");

  mountTarget.innerHTML = `
    <section style="
      padding: 12px;
      color: var(--vscode-errorForeground, #f48771);
      font-family: var(--vscode-font-family, 'Segoe UI', sans-serif);
      line-height: 1.5;
    ">
      <strong style="display:block; margin-bottom:8px;">${escapeHtml(summary)}</strong>
      <pre style="
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 10px;
        color: var(--vscode-foreground, #cccccc);
      ">${escapeHtml(detail)}</pre>
    </section>
  `;
}

/**
 * 转义错误文本中的 HTML 字符，避免错误面板二次解析。
 */
function escapeHtml(source: string): string {
  return source
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
