// 文件说明：
// 本文件封装 VS Code Webview API，供 Vue 组件统一发送消息与保存本地状态。

// 类型说明：
// 描述 Webview 环境下可访问的 VS Code API 形态。
type VsCodeApi = {
  postMessage(message: unknown): void;
  getState(): unknown;
  setState(state: unknown): void;
};

declare global {
  interface Window {
    acquireVsCodeApi: () => VsCodeApi;
  }
}

let cachedVsCodeApi: VsCodeApi | null = null;

/**
 * 惰性获取 Webview 环境下的 VS Code API。
 * 这样可以避免模块初始化阶段直接访问宿主对象而导致整块界面空白。
 */
export function getVsCodeApi(): VsCodeApi {
  if (cachedVsCodeApi) {
    return cachedVsCodeApi;
  }

  if (typeof window.acquireVsCodeApi !== "function") {
    cachedVsCodeApi = {
      postMessage: () => undefined,
      getState: () => undefined,
      setState: () => undefined,
    };
    return cachedVsCodeApi;
  }

  cachedVsCodeApi = window.acquireVsCodeApi();
  return cachedVsCodeApi;
}
