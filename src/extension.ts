import * as vscode from "vscode";
import { AssistantPanelProvider } from "./panels/assistantPanel";

// 文件说明：
// 本文件是 VS Code 插件端入口。
// 其职责包括扩展激活、命令注册、侧边栏挂载以及编辑器上下文刷新。


// 函数说明：
// 当扩展被 VS Code 激活时，完成命令和侧边栏注册。
export function activate(context: vscode.ExtensionContext): void {
  console.log("[Vibe Coding Agent] Extension activated.");

  const panelProvider = new AssistantPanelProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(AssistantPanelProvider.viewType, panelProvider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("vibeCodingAgent.start", async () => {
      console.log("[Vibe Coding Agent] Opening assistant panel.");
      await vscode.commands.executeCommand("workbench.view.extension.vibeCodingAgent");
      panelProvider.reveal();
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => {
      panelProvider.refreshContext();
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeTextEditorSelection(() => {
      panelProvider.refreshContext();
    })
  );

  if (context.extensionMode === vscode.ExtensionMode.Development) {
    setTimeout(async () => {
      try {
        console.log("[Vibe Coding Agent] Auto-opening sidebar in development mode.");
        await vscode.commands.executeCommand("workbench.view.extension.vibeCodingAgent");
        panelProvider.reveal();
      } catch (error) {
        console.error("[Vibe Coding Agent] Failed to auto-open sidebar.", error);
      }
    }, 1200);
  }
}


// 函数说明：
// 当扩展被停用时输出日志，便于调试生命周期。
export function deactivate(): void {
  console.log("[Vibe Coding Agent] Extension deactivated.");
}
