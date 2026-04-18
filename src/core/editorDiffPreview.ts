import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { AgentAction } from "./types";

/**
 * 管理编辑器中的原生 diff 预览。
 *
 * 该服务只负责展示待确认变更，不负责真正写回工作区文件。
 */
export class EditorDiffPreviewService implements vscode.TextDocumentContentProvider, vscode.Disposable {
  public static readonly scheme = "vibe-agent-preview";

  private readonly onDidChangeEmitter = new vscode.EventEmitter<vscode.Uri>();
  private readonly virtualDocuments = new Map<string, string>();
  private lastStreamingTarget?: string;

  public readonly onDidChange = this.onDidChangeEmitter.event;

  /**
   * 返回指定虚拟文档的当前文本内容。
   */
  public provideTextDocumentContent(uri: vscode.Uri): string {
    return this.virtualDocuments.get(uri.toString()) ?? "";
  }

  /**
   * 为项目级待确认方案打开原生 diff 预览。
   *
   * 当前限制最多自动打开前 5 个文件，避免一次性弹出过多标签页。
   * 首个 diff 会切到前台，确保用户能直接看到编辑器中的红绿标注。
   */
  public async showProposalDiffs(actions: AgentAction[], workspaceRoot?: string): Promise<void> {
    const previewTargets = actions.slice(0, 5);

    for (const [index, action] of previewTargets.entries()) {
      await this.openActionDiff(action, workspaceRoot, {
        preview: false,
        preserveFocus: index !== 0,
      });
    }
  }

  /**
   * 在流式 patch 生成过程中复用同一个 diff 预览窗口。
   */
  public async showStreamingDiff(action: AgentAction, workspaceRoot?: string): Promise<void> {
    const targetKey = this.normalizeFilePath(action.targetFile);
    const shouldReveal = this.lastStreamingTarget !== targetKey;

    this.lastStreamingTarget = targetKey;
    await this.openActionDiff(action, workspaceRoot, {
      preview: false,
      preserveFocus: false,
      reveal: shouldReveal,
    });
  }

  /**
   * 清理当前流式预览会话的目标标识。
   */
  public clearStreamingSession(): void {
    this.lastStreamingTarget = undefined;
  }

  /**
   * 释放内部事件对象。
   */
  public dispose(): void {
    this.onDidChangeEmitter.dispose();
  }

  /**
   * 根据动作内容准备左右两侧文档，并打开 VS Code 原生 diff 视图。
   */
  private async openActionDiff(
    action: AgentAction,
    workspaceRoot: string | undefined,
    options: {
      preview: boolean;
      preserveFocus: boolean;
      reveal?: boolean;
    },
  ): Promise<void> {
    const leftUri = this.resolveOriginalUri(action);
    const rightUri = this.buildVirtualUri(action, "updated");

    if (leftUri.scheme === EditorDiffPreviewService.scheme) {
      this.updateVirtualDocument(leftUri, action.originalContent);
    }

    this.updateVirtualDocument(rightUri, action.updatedContent);

    if (options.reveal === false) {
      return;
    }

    const title = this.buildDiffTitle(action, workspaceRoot);
    await vscode.commands.executeCommand(
      "vscode.diff",
      leftUri,
      rightUri,
      title,
      {
        preview: options.preview,
        preserveFocus: options.preserveFocus,
      },
    );
  }

  /**
   * 为 diff 左侧优先返回真实文件 URI；如果文件尚不存在，则退回到虚拟文档。
   */
  private resolveOriginalUri(action: AgentAction): vscode.Uri {
    const targetUri = vscode.Uri.file(action.targetFile);
    const fileExists = fs.existsSync(action.targetFile);

    if (action.kind !== "create_file" && fileExists) {
      return targetUri;
    }

    return this.buildVirtualUri(action, "original");
  }

  /**
   * 为预览文档生成稳定的虚拟 URI，便于重复刷新。
   */
  private buildVirtualUri(action: AgentAction, side: "original" | "updated"): vscode.Uri {
    const fileName = path.basename(action.targetFile) || "preview";
    const query = new URLSearchParams({
      target: action.targetFile,
      side,
      kind: action.kind,
    });

    return vscode.Uri.from({
      scheme: EditorDiffPreviewService.scheme,
      path: `/${fileName}.${side}`,
      query: query.toString(),
    });
  }

  /**
   * 更新虚拟文档内容，并通知 VS Code 刷新对应的 diff 视图。
   */
  private updateVirtualDocument(uri: vscode.Uri, content: string): void {
    this.virtualDocuments.set(uri.toString(), content);
    this.onDidChangeEmitter.fire(uri);
  }

  /**
   * 构造 diff 视图标题，优先展示工作区相对路径。
   */
  private buildDiffTitle(action: AgentAction, workspaceRoot?: string): string {
    const displayPath = this.toDisplayPath(action.targetFile, workspaceRoot);

    if (action.kind === "create_file") {
      return `Code Agent Preview: ${displayPath} (new file)`;
    }

    return `Code Agent Preview: ${displayPath}`;
  }

  /**
   * 将目标路径转换为更适合界面展示的工作区相对路径。
   */
  private toDisplayPath(targetFile: string, workspaceRoot?: string): string {
    if (!workspaceRoot) {
      return targetFile;
    }

    const relativePath = path.relative(workspaceRoot, targetFile);
    if (!relativePath.startsWith("..") && relativePath !== "") {
      return relativePath;
    }

    return targetFile;
  }

  /**
   * 统一路径格式，避免 Windows 下盘符大小写差异造成误判。
   */
  private normalizeFilePath(filePath: string): string {
    const resolved = path.resolve(filePath);
    if (process.platform === "win32") {
      return resolved.replace(/\//g, "\\").toLowerCase();
    }

    return resolved;
  }
}
