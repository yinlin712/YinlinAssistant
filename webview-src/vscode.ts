// 文件说明：
// 本文件封装 VS Code Webview API，供 React 组件统一发送消息与保存本地状态。

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

// 常量说明：
// 暴露单例化的 VS Code API，避免各组件重复获取。
export const vscode = window.acquireVsCodeApi();
