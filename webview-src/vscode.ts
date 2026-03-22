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

export const vscode = window.acquireVsCodeApi();
