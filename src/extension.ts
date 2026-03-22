import * as vscode from "vscode";
import { AssistantPanelProvider } from "./panels/assistantPanel";

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

export function deactivate(): void {
  console.log("[Vibe Coding Agent] Extension deactivated.");
}
