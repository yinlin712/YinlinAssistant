import * as vscode from "vscode";
import { EditorDiffPreviewService } from "./core/editorDiffPreview";
import { AssistantPanelProvider } from "./panels/assistantPanel";

// 文件说明：
// 本文件是 VS Code 插件端入口。
// 其职责包括扩展激活、命令注册、侧边栏挂载以及编辑器上下文刷新。


// 函数说明：
// 当扩展被 VS Code 激活时，完成命令和侧边栏注册。
export function activate(context: vscode.ExtensionContext): void {
  console.log("[Code Agent] Extension activated.");

  const diffPreviewService = new EditorDiffPreviewService();
  const panelProvider = new AssistantPanelProvider(context.extensionUri, diffPreviewService);

  context.subscriptions.push(
    diffPreviewService,
    vscode.workspace.registerTextDocumentContentProvider(
      EditorDiffPreviewService.scheme,
      diffPreviewService,
    ),
    vscode.window.registerWebviewViewProvider(
      AssistantPanelProvider.viewType,
      panelProvider,
      {
        webviewOptions: {
          retainContextWhenHidden: true,
        },
      },
    )
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("vibeCodingAgent.start", async () => {
      console.log("[Code Agent] Opening assistant panel.");
      await vscode.commands.executeCommand("workbench.view.extension.vibeCodingAgent");
      panelProvider.reveal();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("vibeCodingAgent.editCurrentFile", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        void vscode.window.showWarningMessage("当前没有活动文件，无法直接修改。");
        return;
      }

      const userInstruction = await vscode.window.showInputBox({
        prompt: "描述希望如何修改当前文件",
        placeHolder: "例如：请把当前函数拆分成更清晰的私有方法，并补上必要的中文注释。",
        ignoreFocusOut: true,
      });

      if (!userInstruction?.trim()) {
        return;
      }

      await vscode.commands.executeCommand("workbench.view.extension.vibeCodingAgent");
      panelProvider.reveal();
      await panelProvider.submitPrompt(`请直接修改当前文件：${userInstruction.trim()}`);
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
        await vscode.commands.executeCommand("workbench.view.extension.vibeCodingAgent");
        panelProvider.reveal();
      } catch (error) {
        console.error("[Code Agent] Failed to auto-open sidebar.", error);
      }
    }, 1200);
  }
}


// 函数说明：
// 当扩展被停用时进行清理。
export function deactivate(): void {
  // 当前版本没有额外的停用清理逻辑。
}
