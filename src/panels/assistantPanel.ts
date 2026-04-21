import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { CodingAgent } from "../core/agent";
import { buildActionPreviewItems } from "../core/diffPreview";
import { EditorDiffPreviewService } from "../core/editorDiffPreview";
import {
  ActionExecutionProgress,
  ActionPreviewItem,
  AgentAction,
  AgentContext,
  AppliedAgentAction,
  ChatMessage,
  ConversationTurn,
} from "../core/types";

/**
 * 集中维护侧边栏中使用的界面文案。
 */
const PANEL_TEXT = {
  greeting: "你好，我是 Code Agent。现在我既可以检索项目并生成多文件预览，也可以直接改写当前活动文件。",
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
  directApplyPrompt: "已经为当前文件生成可直接写回的修改方案。是否立即应用？",
  directApplyNow: "立即应用",
  previewOnly: "先看预览",
  streaming: "流式写回中",
  streamingTitle: "实时 patch 预览",
  streamingSummary: "模型正在生成当前文件的修改内容。",
  streamingPlanSummary: "正在生成当前文件的修改方案。",
  streamingApplyBlocked: "当前 patch 仍在生成中，请等待完整结果返回后再应用。",
};

interface PendingProposal {
  actions: AgentAction[];
  summary: string;
  previews: ActionPreviewItem[];
  context: AgentContext;
  isStreaming: boolean;
}

interface AvatarResources {
  enabled: boolean;
  mode: "prototype" | "vrm" | "airi-ready";
  avatarUri?: vscode.Uri | string;
  vrmUri?: vscode.Uri | string;
  defaultPresetId: string;
  presets: AvatarPresetResource[];
  localRoots: vscode.Uri[];
}

interface AvatarPresetResource {
  id: string;
  label: string;
  avatarUri?: vscode.Uri | string;
  vrmUri?: vscode.Uri | string;
}

interface AvatarPresetManifestItem {
  id: string;
  label: string;
  avatarUri?: string;
  vrmUri?: string;
}

/**
 * 统一管理 Webview 生命周期、消息分发和待确认方案状态。
 */
export class AssistantPanelProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "vibeCodingAgent.sidebar";

  private view?: vscode.WebviewView;
  private readonly agent = new CodingAgent();
  private readonly sessionId = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  private readonly messages: ChatMessage[] = [
    {
      role: "agent",
      content: PANEL_TEXT.greeting,
    },
  ];

  private pendingProposal?: PendingProposal;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly diffPreviewService: EditorDiffPreviewService,
  ) {}

  /**
   * 在 Webview 首次解析时完成资源注入、消息监听与初始状态同步。
   */
  public resolveWebviewView(webviewView: vscode.WebviewView): void {
    this.view = webviewView;
    const avatarResources = this.resolveAvatarResources(webviewView.webview);
    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this.extensionUri, "media"),
        vscode.Uri.joinPath(this.extensionUri, "backend"),
        ...avatarResources.localRoots,
      ],
    };

    webviewView.webview.html = this.getHtml(webviewView.webview, avatarResources);

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

  /**
   * 主动显示已经创建好的侧边栏视图。
   */
  public reveal(): void {
    this.view?.show?.(true);
  }

  /**
   * 供命令面板等入口主动提交提示词到当前面板。
   */
  public async submitPrompt(rawPrompt: string): Promise<void> {
    await this.handleSubmitPrompt(rawPrompt);
  }

  /**
   * 当编辑器上下文变化时刷新顶部状态栏。
   */
  public refreshContext(): void {
    this.postStatus(PANEL_TEXT.idle);
  }

  /**
   * 接收用户输入并调用插件端 Agent，随后将结果推送给 Webview。
   */
  private async handleSubmitPrompt(rawPrompt: string): Promise<void> {
    const prompt = rawPrompt.trim();
    if (!prompt) {
      return;
    }

    this.diffPreviewService.clearStreamingSession();
    this.clearPendingProposal();

    const conversationHistory = this.buildConversationHistory();
    this.messages.push({ role: "user", content: prompt });
    this.postMessage("message", { role: "user", content: prompt });
    this.postStatus(PANEL_TEXT.thinking);

    const result = await this.agent.streamRun(prompt, conversationHistory, {
      onPatchPreview: (updatedContent, context) => this.showStreamingPatchPreview(updatedContent, context),
      onMessageChunk: (chunk) => this.postMessage("messageChunk", { role: "agent", chunk }),
      onStatus: (status) => this.postStatus(status),
    });

    this.messages.push({
      role: "agent",
      content: result.response.content,
    });

    this.postMessage("message", {
      role: "agent",
      content: result.response.content,
    });

    const hasExecutableActions = result.response.actions.length > 0;
    const shouldShowProposal = hasExecutableActions
      && (result.response.requiresConfirmation || result.response.autoApplyActions);

    if (shouldShowProposal) {
      const previews = buildActionPreviewItems(result.response.actions, result.context.workspaceRoot);
      const summary = result.response.proposalSummary || `共生成 ${previews.length} 个待确认变更。`;

      this.pendingProposal = {
        actions: result.response.actions,
        summary,
        previews,
        context: result.context,
        isStreaming: false,
      };

      this.postMessage("proposal", {
        title: PANEL_TEXT.proposalTitle,
        summary,
        actions: previews,
        isStreaming: false,
      });

      await this.diffPreviewService.showProposalDiffs(result.response.actions, result.context.workspaceRoot);
    } else {
      this.clearPendingProposal();
    }

    if (result.response.autoApplyActions && hasExecutableActions) {
      const choice = await vscode.window.showInformationMessage(
        PANEL_TEXT.directApplyPrompt,
        PANEL_TEXT.directApplyNow,
        PANEL_TEXT.previewOnly,
      );

      if (choice === PANEL_TEXT.directApplyNow) {
        await this.applyPendingActions();
        return;
      }
    }

    this.postStatus(this.moodToStatus(result.response.mood), result.provider, result.context.activeFile);
  }

  /**
   * 在用户确认后执行待确认文件动作，并回写执行结果。
   */
  private async applyPendingActions(): Promise<void> {
    if (!this.pendingProposal) {
      return;
    }

    if (this.pendingProposal.isStreaming) {
      void vscode.window.showInformationMessage(PANEL_TEXT.streamingApplyBlocked);
      return;
    }

    this.postStatus(PANEL_TEXT.applying);

    const result = await this.agent.applyProposedActions(
      this.pendingProposal.actions,
      this.pendingProposal.context,
      {
        onProgress: (progress) => this.handleApplyProgress(progress),
      },
    );

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

    this.clearPendingProposal();
    this.postStatus(PANEL_TEXT.responded, undefined, result.context.activeFile);
  }

  /**
   * 向前端发送初始消息、状态信息和历史记录。
   */
  private postHydrate(): void {
    const provider = vscode.workspace
      .getConfiguration("vibeCodingAgent")
      .get<string>("modelProvider", "local");

    this.postMessage("hydrate", {
      sessionId: this.sessionId,
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
            isStreaming: this.pendingProposal.isStreaming,
          }
        : null,
    });
  }

  /**
   * 清空当前待确认方案，并按需通知前端重置预览区域。
   */
  private clearPendingProposal(notifyWebview: boolean = true): void {
    this.pendingProposal = undefined;
    this.diffPreviewService.clearStreamingSession();

    if (notifyWebview) {
      this.postMessage("clearProposal", {
        title: PANEL_TEXT.proposalTitle,
        emptyText: PANEL_TEXT.proposalEmpty,
      });
    }
  }

  /**
   * 更新前端顶部状态栏，展示当前状态、模型提供者和活动文件。
   */
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

  /**
   * 统一向 Webview 发送结构化消息。
   */
  private postMessage(type: string, payload: unknown): void {
    this.view?.webview.postMessage({ type, payload });
  }

  /**
   * 将文件写回过程中的阶段性进度映射到状态栏。
   */
  private handleApplyProgress(progress: ActionExecutionProgress): void {
    const shortPath = this.toShortPath(progress.targetFile);
    this.postStatus(`${PANEL_TEXT.streaming} ${progress.percent}%`, undefined, shortPath);
  }

  /**
   * 将最近几轮用户与助手消息整理为后端可消费的对话上下文。
   */
  private buildConversationHistory(): ConversationTurn[] {
    return this.messages
      .filter((message): message is ChatMessage & { role: "user" | "agent" } => (
        message.role === "user" || message.role === "agent"
      ))
      .slice(-6)
      .map((message) => ({
        role: message.role,
        content: message.content,
      }));
  }

  /**
   * 在模型流式生成当前文件内容时，实时展示 patch 预览。
   */
  private showStreamingPatchPreview(updatedContent: string, context: AgentContext): void {
    if (!context.activeFile || !context.fullDocumentText || !updatedContent.trim()) {
      return;
    }

    const draftAction: AgentAction = {
      kind: "update_file",
      targetFile: context.activeFile,
      originalContent: context.fullDocumentText,
      updatedContent,
      summary: "实时 patch 预览",
    };
    const previews = buildActionPreviewItems([draftAction], context.workspaceRoot);

    this.pendingProposal = {
      actions: [draftAction],
      summary: PANEL_TEXT.streamingPlanSummary,
      previews,
      context,
      isStreaming: true,
    };

    this.postMessage("proposal", {
      title: PANEL_TEXT.streamingTitle,
      summary: PANEL_TEXT.streamingSummary,
      actions: previews,
      isStreaming: true,
    });

    void this.diffPreviewService.showStreamingDiff(draftAction, context.workspaceRoot);
  }

  /**
   * 生成 Webview 页面所需的 HTML 外壳，并注入脚本、样式和头像资源。
   */
  private getHtml(webview: vscode.Webview, avatarResources: AvatarResources): string {
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "webview.js"));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", "styles.css"));
    const avatarUri = this.toWebviewResourceUri(webview, avatarResources.avatarUri);
    const avatarVrmUri = this.toWebviewResourceUri(webview, avatarResources.vrmUri);
    const avatarConfig = JSON.stringify({
      enabled: avatarResources.enabled,
      mode: avatarResources.mode,
      avatarUri,
      vrmUri: avatarVrmUri,
      defaultPresetId: avatarResources.defaultPresetId,
      presets: avatarResources.presets.map((preset) => ({
        id: preset.id,
        label: preset.label,
        avatarUri: this.toWebviewResourceUri(webview, preset.avatarUri),
        vrmUri: this.toWebviewResourceUri(webview, preset.vrmUri),
      })),
    }).replace(/</g, "\\u003c");

    return `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link rel="stylesheet" href="${styleUri}" />
    <title>Code Agent</title>
  </head>
  <body
    data-session-id="${this.sessionId}"
  >
    <div id="root">
      <section style="
        padding: 12px;
        color: var(--vscode-descriptionForeground, #8a8a8a);
        font-family: var(--vscode-font-family, 'Segoe UI', sans-serif);
        line-height: 1.5;
      ">
        Code Agent 正在初始化...
      </section>
    </div>
    <script id="code-agent-avatar-config" type="application/json">${avatarConfig}</script>
    <script>
      globalThis.process = globalThis.process || { env: {} };
      globalThis.process.env = globalThis.process.env || {};
      globalThis.process.env.NODE_ENV = globalThis.process.env.NODE_ENV || "production";
    </script>
    <script src="${scriptUri}"></script>
  </body>
</html>`;
  }

  /**
   * 读取插件配置中的数字人资源，并转换为 Webview 可访问的 URI。
   */
  private resolveAvatarResources(_webview: vscode.Webview): AvatarResources {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const enabled = config.get<boolean>("enableAvatar", true);
    const rawMode = config.get<string>("avatarMode", "vrm");
    const mode = rawMode === "vrm" || rawMode === "airi-ready"
      ? rawMode
      : "prototype";
    const defaultAvatarUri = vscode.Uri.joinPath(this.extensionUri, "backend", "icon.jpg");
    const presetCatalogPath = vscode.Uri.joinPath(this.extensionUri, "virtual", "avatar-presets.json");
    const avatarVrmPath = config.get<string>("avatarVrmPath", "").trim();

    const resources: AvatarResources = {
      enabled,
      mode,
      avatarUri: defaultAvatarUri,
      defaultPresetId: "",
      presets: [],
      localRoots: [],
    };

    const presetCatalog = this.loadAvatarPresetCatalog(presetCatalogPath.fsPath);
    for (const item of presetCatalog) {
      const preset: AvatarPresetResource = {
        id: item.id,
        label: item.label,
        avatarUri: this.resolveAvatarManifestResource(item.avatarUri) ?? defaultAvatarUri,
        vrmUri: this.resolveAvatarManifestResource(item.vrmUri),
      };

      resources.presets.push(preset);
      this.collectAvatarLocalRoot(resources.localRoots, preset.avatarUri);
      this.collectAvatarLocalRoot(resources.localRoots, preset.vrmUri);
    }

    if (avatarVrmPath) {
      const resolvedVrmPath = path.resolve(avatarVrmPath);
      if (fs.existsSync(resolvedVrmPath) && fs.statSync(resolvedVrmPath).isFile()) {
        const customVrmUri = vscode.Uri.file(resolvedVrmPath);
        resources.presets.unshift({
          id: "custom-local",
          label: "\u5c0f\u7814",
          avatarUri: defaultAvatarUri,
          vrmUri: customVrmUri,
        });
        this.collectAvatarLocalRoot(resources.localRoots, customVrmUri);
      }
    }

    const primaryPreset = resources.presets[0];
    resources.defaultPresetId = primaryPreset?.id ?? "default-code-agent";
    resources.avatarUri = primaryPreset?.avatarUri ?? defaultAvatarUri;
    resources.vrmUri = primaryPreset?.vrmUri;

    if (!primaryPreset) {
      resources.presets.push({
        id: resources.defaultPresetId,
        label: "\u5c0f\u6f9c",
        avatarUri: defaultAvatarUri,
      });
    }

    return resources;
  }

  /**
   * ????? virtual ????????????
   */
  private loadAvatarPresetCatalog(filePath: string): AvatarPresetManifestItem[] {
    if (!fs.existsSync(filePath)) {
      return [];
    }

    try {
      const raw = fs.readFileSync(filePath, "utf8");
      const parsed = JSON.parse(raw) as Partial<AvatarPresetManifestItem>[];
      if (!Array.isArray(parsed)) {
        return [];
      }

      return parsed
        .filter((item): item is AvatarPresetManifestItem => Boolean(item?.id && item?.label))
        .map((item) => ({
          id: item.id,
          label: item.label,
          avatarUri: item.avatarUri?.trim() || undefined,
          vrmUri: item.vrmUri?.trim() || undefined,
        }));
    } catch (error) {
      console.error("[Code Agent] Failed to load avatar preset catalog.", error);
      return [];
    }
  }

  /**
   * ????????????????????????
   */
  private resolveAvatarManifestResource(resource?: string): vscode.Uri | string | undefined {
    if (!resource) {
      return undefined;
    }

    if (/^https?:\/\//i.test(resource)) {
      return resource;
    }

    if (path.isAbsolute(resource)) {
      return vscode.Uri.file(resource);
    }

    return vscode.Uri.joinPath(this.extensionUri, "virtual", resource);
  }

  /**
   * ?? Webview ??????????????????
   */
  private collectAvatarLocalRoot(targetRoots: vscode.Uri[], resource?: vscode.Uri | string): void {
    if (!(resource instanceof vscode.Uri) || resource.scheme !== "file") {
      return;
    }

    const directory = vscode.Uri.file(path.dirname(resource.fsPath));
    if (!targetRoots.some((root) => root.fsPath === directory.fsPath)) {
      targetRoots.push(directory);
    }
  }

  private toWebviewResourceUri(
    webview: vscode.Webview,
    resource?: vscode.Uri | string,
  ): string {
    if (!resource) {
      return "";
    }

    if (typeof resource === "string") {
      return resource;
    }

    return webview.asWebviewUri(resource).toString();
  }

  /**
   * 将后端返回的工作状态映射为界面文案。
   */
  private moodToStatus(mood: "idle" | "thinking" | "helpful"): string {
    if (mood === "thinking") {
      return PANEL_TEXT.thinking;
    }

    if (mood === "helpful") {
      return PANEL_TEXT.responded;
    }

    return PANEL_TEXT.idle;
  }

  /**
   * 将文件动作执行结果格式化为对话区可展示的系统消息。
   */
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

  /**
   * 在存在工作区根目录时，将绝对路径转换为相对路径以便阅读。
   */
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
