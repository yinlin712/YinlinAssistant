import * as path from "path";
import * as vscode from "vscode";
import { CodingAgent } from "../core/agent";
import { buildActionPreviewItems } from "../core/diffPreview";
import { ActionPreviewItem, AgentAction, AppliedAgentAction, ChatMessage } from "../core/types";

// 文件说明：
// 本文件负责在 VS Code 侧边栏中挂载 Webview，并完成插件端与前端界面的消息桥接。

// 常量说明：
// 集中维护侧边栏界面使用的静态文案，避免分散在业务逻辑中。
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

// 类型说明：
// 保存当前待确认的变更方案及其 diff 预览结果。
interface PendingProposal {
  actions: AgentAction[];
  summary: string;
  previews: ActionPreviewItem[];
}

// 类说明：
// 统一管理 Webview 生命周期、消息分发和待确认方案状态。
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

  // 方法说明：
  // 在 Webview 首次解析时完成资源注入、消息监听与初始状态同步。
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

  // 方法说明：
  // 主动显示已经创建好的侧边栏视图。
  public reveal(): void {
    this.view?.show?.(true);
  }

  // 方法说明：
  // 当编辑器上下文变化时刷新顶部状态栏。
  public refreshContext(): void {
    this.postStatus(PANEL_TEXT.idle);
  }

  // 方法说明：
  // 接收用户输入并调用插件侧 Agent，随后将结果推送给 Webview。
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

  // 方法说明：
  // 在用户确认后执行待确认文件动作，并回写执行结果。
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

  // 方法说明：
  // 向前端发送初始消息、状态信息和历史记录。
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

  // 方法说明：
  // 清空当前待确认方案，并按需通知前端重置预览区域。
  private clearPendingProposal(notifyWebview: boolean = true): void {
    this.pendingProposal = undefined;
    if (notifyWebview) {
      this.postMessage("clearProposal", {
        title: PANEL_TEXT.proposalTitle,
        emptyText: PANEL_TEXT.proposalEmpty,
      });
    }
  }

  // 方法说明：
  // 更新前端顶部状态栏，展示当前状态、模型提供者和活动文件。
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

  // 方法说明：
  // 统一向 Webview 发送结构化消息。
  private postMessage(type: string, payload: unknown): void {
    this.view?.webview.postMessage({ type, payload });
  }

  // 方法说明：
  // 生成 Webview 页面所需的 HTML 外壳，并注入脚本、样式和头像资源。
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

  // 方法说明：
  // 将后端返回的工作状态映射为界面展示文案。
  private moodToStatus(mood: "idle" | "thinking" | "helpful"): string {
    if (mood === "thinking") {
      return PANEL_TEXT.thinking;
    }

    if (mood === "helpful") {
      return PANEL_TEXT.responded;
    }

    return PANEL_TEXT.idle;
  }

  // 方法说明：
  // 将文件动作执行结果格式化为对话区可展示的系统消息。
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

  // 方法说明：
  // 在存在工作区根目录时，将绝对路径转换为相对路径以便阅读。
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
