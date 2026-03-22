import * as path from "path";
import * as vscode from "vscode";
import { CodingAgent } from "../core/agent";
import { buildActionPreviewItems } from "../core/diffPreview";
import { ActionPreviewItem, AgentAction, AppliedAgentAction, ChatMessage } from "../core/types";

const PANEL_TEXT = {
  greeting: "你好，我是 Vibe Coding Agent。现在我可以先检索项目相关文件，再生成待确认的多文件修改预览。",
  idle: "待命",
  thinking: "思考中",
  applying: "应用中",
  responded: "已响应",
  noActiveFile: "无活动文件",
  proposalTitle: "待确认变更",
  proposalEmpty: "当前还没有待确认的变更方案。",
  appliedPrefix: "已执行文件修改",
  skippedPrefix: "未执行文件修改",
  failedPrefix: "文件修改失败",
};

interface PendingProposal {
  actions: AgentAction[];
  summary: string;
  previews: ActionPreviewItem[];
}

export class AssistantPanelProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "vibeCodingAgent.sidebar";

  private view?: vscode.WebviewView;
  private readonly agent = new CodingAgent();
  private readonly messages: ChatMessage[] = [
    {
      role: "agent",
      content: PANEL_TEXT.greeting,
    },
  ];

  private pendingProposal?: PendingProposal;

  constructor(private readonly extensionUri: vscode.Uri) {}

  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, "media"),
        vscode.Uri.joinPath(this.extensionUri, "backend"),
      ],
    };

    webviewView.webview.html = this.getHtml(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (message) => {
      if (message.type === "submitPrompt") {
        await this.handleSubmitPrompt(String(message.payload?.prompt ?? ""));
      }

      if (message.type === "applyPendingActions") {
        await this.applyPendingActions();
      }

      if (message.type === "discardPendingActions") {
        this.clearPendingProposal();
      }
    });

    this.postHydrate();
  }

  public reveal(): void {
    this.view?.show?.(true);
  }

  public refreshContext(): void {
    this.postStatus(PANEL_TEXT.idle);
  }

  private async handleSubmitPrompt(rawPrompt: string): Promise<void> {
    const prompt = rawPrompt.trim();
    if (!prompt) {
      return;
    }

    this.messages.push({ role: "user", content: prompt });
    this.postMessage("message", { role: "user", content: prompt });
    this.postStatus(PANEL_TEXT.thinking);

    const result = await this.agent.run(prompt);

    this.messages.push({
      role: "agent",
      content: result.response.content,
    });

    this.postMessage("message", {
      role: "agent",
      content: result.response.content,
    });

    if (result.response.requiresConfirmation && result.response.actions.length > 0) {
      const previews = buildActionPreviewItems(result.response.actions, result.context.workspaceRoot);
      const summary = result.response.proposalSummary || `共生成 ${previews.length} 个待确认变更。`;
      this.pendingProposal = {
        actions: result.response.actions,
        summary,
        previews,
      };

      this.postMessage("proposal", {
        title: PANEL_TEXT.proposalTitle,
        summary,
        actions: previews,
      });
    } else {
      this.clearPendingProposal(false);
    }

    this.postStatus(this.moodToStatus(result.response.mood), result.provider, result.context.activeFile);
  }

  private async applyPendingActions(): Promise<void> {
    if (!this.pendingProposal) {
      return;
    }

    this.postStatus(PANEL_TEXT.applying);

    const result = await this.agent.applyProposedActions(this.pendingProposal.actions);
    for (const action of result.appliedActions) {
      const actionMessage = this.describeAppliedAction(action);
      this.messages.push({
        role: "system",
        content: actionMessage,
      });
      this.postMessage("message", {
        role: "system",
        content: actionMessage,
      });
    }

    this.clearPendingProposal(false);
    this.postStatus(PANEL_TEXT.responded, undefined, result.context.activeFile);
  }

  private postHydrate(): void {
    const provider = vscode.workspace
      .getConfiguration("vibeCodingAgent")
      .get<string>("modelProvider", "local");

    this.postMessage("hydrate", {
      messages: this.messages,
      status: PANEL_TEXT.idle,
      provider,
      activeFile: vscode.window.activeTextEditor?.document.fileName,
      noActiveFile: PANEL_TEXT.noActiveFile,
      proposalTitle: PANEL_TEXT.proposalTitle,
      proposalEmpty: PANEL_TEXT.proposalEmpty,
      pendingProposal: this.pendingProposal
        ? {
            title: PANEL_TEXT.proposalTitle,
            summary: this.pendingProposal.summary,
            actions: this.pendingProposal.previews,
          }
        : null,
    });
  }

  private clearPendingProposal(notifyWebview: boolean = true): void {
    this.pendingProposal = undefined;
    if (notifyWebview) {
      this.postMessage("clearProposal", {
        title: PANEL_TEXT.proposalTitle,
        emptyText: PANEL_TEXT.proposalEmpty,
      });
    }
  }

  private postStatus(status: string, provider?: string, activeFile?: string): void {
    const resolvedProvider = provider ?? vscode.workspace
      .getConfiguration("vibeCodingAgent")
      .get<string>("modelProvider", "local");

    this.postMessage("status", {
      status,
      provider: resolvedProvider,
      activeFile: activeFile ?? vscode.window.activeTextEditor?.document.fileName,
      noActiveFile: PANEL_TEXT.noActiveFile,
    });
  }

  private postMessage(type: string, payload: unknown): void {
    this.view?.webview.postMessage({ type, payload });
  }

  private getHtml(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "webview.js"));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "styles.css"));
    const avatarUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "backend", "icon.jpg"));

    return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="stylesheet" href="${styleUri}" />
    <title>Vibe Coding Agent</title>
  </head>
  <body data-avatar-uri="${avatarUri}">
    <div id="root"></div>
    <script src="${scriptUri}"></script>
  </body>
</html>`;
  }

  private moodToStatus(mood: "idle" | "thinking" | "helpful"): string {
    if (mood === "thinking") {
      return PANEL_TEXT.thinking;
    }

    if (mood === "helpful") {
      return PANEL_TEXT.responded;
    }

    return PANEL_TEXT.idle;
  }

  private describeAppliedAction(action: AppliedAgentAction): string {
    const shortPath = this.toShortPath(action.targetFile);

    if (action.status === "applied") {
      return `${PANEL_TEXT.appliedPrefix}\n文件：${shortPath}\n说明：${action.summary}`;
    }

    if (action.status === "skipped") {
      return `${PANEL_TEXT.skippedPrefix}\n文件：${shortPath}\n原因：${action.summary}`;
    }

    return `${PANEL_TEXT.failedPrefix}\n文件：${shortPath}\n原因：${action.summary}`;
  }

  private toShortPath(filePath: string): string {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
      return filePath;
    }

    const relativePath = path.relative(workspaceRoot, filePath);
    if (!relativePath.startsWith("..") && relativePath !== "") {
      return relativePath;
    }

    return filePath;
  }
}
