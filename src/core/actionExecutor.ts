import * as path from "path";
import * as vscode from "vscode";
import { ActionExecutionProgress, AgentAction, AgentContext, AppliedAgentAction } from "./types";

// 文件说明：
// 本文件负责在插件端真正执行文件动作。
// 后端只负责规划，实际写入工作区文件必须由插件端完成。


// 类说明：
// 统一处理创建文件、更新代码文件和更新文档文件三类动作。
export class AgentActionExecutor {
  // 方法说明：
  // 顺序执行动作列表，并为每个动作返回执行结果。
  public async execute(
    actions: AgentAction[],
    context: AgentContext,
    options?: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<AppliedAgentAction[]> {
    const results: AppliedAgentAction[] = [];

    for (const action of actions) {
      switch (action.kind) {
        case "create_file":
          results.push(await this.createFile(action, context, options));
          break;
        case "update_file":
          results.push(await this.updateExistingFile(action, context, options));
          break;
        case "update_documentation":
          results.push(await this.updateDocumentation(action, context, options));
          break;
      }
    }

    return results;
  }

  // 方法说明：
  // 执行“新建文件”动作。
  private async createFile(
    action: AgentAction,
    context: AgentContext,
    options?: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<AppliedAgentAction> {
    try {
      const targetPath = this.ensureAllowedPath(action.targetFile, context);
      if (!targetPath) {
        return this.buildResult(action, "skipped", "目标路径不在当前工作区内，因此不会创建文件。");
      }

      const existingContent = await this.readCurrentText(targetPath);
      if (existingContent !== null) {
        return this.buildResult(action, "skipped", "目标文件已经存在，因此这次没有按 create_file 创建。");
      }

      this.reportProgress(options, targetPath, 10, "准备创建文件");
      await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(targetPath)));
      await this.writeTextToDisk(targetPath, action.updatedContent);
      this.reportProgress(options, targetPath, 100, "文件创建完成");
      return this.buildResult(action, "applied", action.summary || "已创建新文件。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  // 方法说明：
  // 执行“更新已有代码文件”动作。
  private async updateExistingFile(
    action: AgentAction,
    context: AgentContext,
    options?: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<AppliedAgentAction> {
    try {
      const targetPath = this.ensureAllowedPath(action.targetFile, context);
      if (!targetPath) {
        return this.buildResult(action, "skipped", "目标路径不在当前工作区内，因此不会更新文件。");
      }

      const currentText = await this.readCurrentText(targetPath);
      if (currentText === null) {
        return this.buildResult(action, "skipped", "目标文件不存在，因此无法按更新动作处理。");
      }

      if (!this.matchesOriginalContent(currentText, action.originalContent)) {
        return this.buildResult(
          action,
          "skipped",
          "目标文件在预览生成后已经发生变化，插件已跳过写回，避免覆盖你的新编辑。"
        );
      }

      const nextText = this.normalizeText(action.updatedContent, currentText);
      if (this.canonicalize(nextText) === this.canonicalize(currentText)) {
        return this.buildResult(action, "skipped", "新内容与当前文件一致，因此无需更新。");
      }

      await this.replaceWholeDocument(targetPath, nextText, {
        streamEdits: this.shouldStreamEdits(targetPath, context),
        onProgress: options?.onProgress,
      });
      return this.buildResult(action, "applied", action.summary || "已更新文件。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  // 方法说明：
  // 执行“更新文档文件”动作。
  private async updateDocumentation(
    action: AgentAction,
    context: AgentContext,
    options?: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<AppliedAgentAction> {
    try {
      const targetPath = this.ensureAllowedPath(action.targetFile, context);
      if (!targetPath) {
        return this.buildResult(action, "skipped", "文档路径不在当前工作区内，因此不会写回。");
      }

      const currentText = await this.readCurrentText(targetPath);
      if (currentText === null) {
        this.reportProgress(options, targetPath, 10, "准备创建文档");
        await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(targetPath)));
        await this.writeTextToDisk(targetPath, action.updatedContent);
        this.reportProgress(options, targetPath, 100, "文档创建完成");
        return this.buildResult(action, "applied", action.summary || "已创建新的文档文件。");
      }

      if (!this.matchesOriginalContent(currentText, action.originalContent)) {
        return this.buildResult(
          action,
          "skipped",
          "文档内容在预览生成后已经变化，因此这次没有自动覆盖。"
        );
      }

      const nextText = this.normalizeText(action.updatedContent, currentText);
      if (this.canonicalize(nextText) === this.canonicalize(currentText)) {
        return this.buildResult(action, "skipped", "文档更新内容与当前文件一致，因此无需写回。");
      }

      await this.replaceWholeDocument(targetPath, nextText, {
        streamEdits: this.shouldStreamEdits(targetPath, context),
        onProgress: options?.onProgress,
      });
      return this.buildResult(action, "applied", action.summary || "已更新文档。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  // 方法说明：
  // 校验目标路径是否位于当前工作区内。
  private ensureAllowedPath(targetFile: string, context: AgentContext): string | undefined {
    if (!targetFile.trim()) {
      return undefined;
    }

    const targetPath = path.resolve(targetFile);
    const activeFile = context.activeFile ? path.resolve(context.activeFile) : undefined;
    if (activeFile && this.isSameFilePath(targetPath, activeFile)) {
      return targetPath;
    }

    const workspaceFolder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(targetPath));
    if (workspaceFolder) {
      return targetPath;
    }

    const isOpenedDocument = vscode.workspace.textDocuments.some(
      (document) => this.isSameFilePath(document.fileName, targetPath),
    );
    if (isOpenedDocument) {
      return targetPath;
    }

    if (!context.workspaceRoot) {
      return undefined;
    }

    const workspaceRoot = path.resolve(context.workspaceRoot);
    if (!this.isInsideWorkspace(targetPath, workspaceRoot)) {
      return undefined;
    }

    return targetPath;
  }

  // 方法说明：
  // 将目标文件整篇替换为新内容。
  private async replaceWholeDocument(
    targetPath: string,
    nextText: string,
    options?: {
      streamEdits?: boolean;
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<void> {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(targetPath));
    const currentText = document.getText();
    const normalizedText = this.normalizeText(nextText, currentText, document.eol);

    if (options?.streamEdits) {
      const editor = await vscode.window.showTextDocument(document, {
        preview: false,
        preserveFocus: false,
      });
      await this.streamDocumentReplacement(editor, normalizedText, options.onProgress);
    } else {
      this.reportProgress({ onProgress: options?.onProgress }, targetPath, 20, "准备写回文件");
      const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(currentText.length));
      const edit = new vscode.WorkspaceEdit();

      edit.replace(document.uri, fullRange, normalizedText);

      const applied = await vscode.workspace.applyEdit(edit);
      if (!applied) {
        throw new Error("VS Code 未能成功应用这次编辑。");
      }
      this.reportProgress({ onProgress: options?.onProgress }, targetPath, 90, "文件内容已更新");
    }

    await document.save();
    this.reportProgress({ onProgress: options?.onProgress }, targetPath, 100, "文件写回完成");
  }

  // 方法说明：
  // 优先从已打开文档中读取内容，否则回退到磁盘读取。
  private async readCurrentText(targetPath: string): Promise<string | null> {
    const openDocument = vscode.workspace.textDocuments.find(
      (document) => this.isSameFilePath(document.fileName, targetPath),
    );
    if (openDocument) {
      return openDocument.getText();
    }

    try {
      const bytes = await vscode.workspace.fs.readFile(vscode.Uri.file(targetPath));
      return Buffer.from(bytes).toString("utf8");
    } catch {
      return null;
    }
  }

  // 方法说明：
  // 将文本写入磁盘文件。
  private async writeTextToDisk(targetPath: string, content: string): Promise<void> {
    const normalized = this.normalizeText(content, "", vscode.EndOfLine.CRLF);
    const bytes = Buffer.from(normalized, "utf8");
    await vscode.workspace.fs.writeFile(vscode.Uri.file(targetPath), bytes);
  }

  // 方法说明：
  // 按目标文件换行风格规范化文本内容。
  private normalizeText(
    updatedContent: string,
    currentContent: string,
    eol: vscode.EndOfLine = vscode.EndOfLine.CRLF
  ): string {
    const normalizedNewlines = updatedContent.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const newline = eol === vscode.EndOfLine.CRLF ? "\r\n" : "\n";
    let result = normalizedNewlines.replace(/\n/g, newline);

    const currentEndsWithNewline = currentContent.endsWith("\n") || currentContent.endsWith("\r\n");
    if (currentEndsWithNewline && !result.endsWith(newline)) {
      result += newline;
    }

    return result;
  }

  // 方法说明：
  // 判断目标文件是否仍与预览时的原始内容一致。
  private matchesOriginalContent(currentText: string, originalContent: string): boolean {
    return this.canonicalize(currentText) === this.canonicalize(originalContent);
  }

  // 方法说明：
  // 统一文本比较时使用的规范化规则。
  private canonicalize(content: string): string {
    return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  }

  // 方法说明：
  // 构造单个动作的执行结果对象。
  private buildResult(
    action: AgentAction,
    status: AppliedAgentAction["status"],
    summary: string
  ): AppliedAgentAction {
    return {
      kind: action.kind,
      targetFile: action.targetFile,
      status,
      summary,
    };
  }

  // 方法说明：
  // 将未知异常统一转换为字符串消息。
  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }

  // 方法说明：
  // 判断目标文件是否应在编辑器中采用流式写回方式。
  private shouldStreamEdits(targetPath: string, context: AgentContext): boolean {
    if (!context.activeFile) {
      return false;
    }

    return this.isSameFilePath(context.activeFile, targetPath);
  }

  // 方法说明：
  // 在编辑器中以分段方式替换全文，从而呈现更接近实时改写的视觉效果。
  private async streamDocumentReplacement(
    editor: vscode.TextEditor,
    nextText: string,
    onProgress?: (progress: ActionExecutionProgress) => void,
  ): Promise<void> {
    const targetFile = editor.document.fileName;
    const chunks = this.buildStreamingChunks(nextText);

    for (let index = 0; index < chunks.length; index += 1) {
      const partialText = chunks[index];
      const currentText = editor.document.getText();
      const fullRange = new vscode.Range(
        editor.document.positionAt(0),
        editor.document.positionAt(currentText.length),
      );

      const applied = await editor.edit(
        (editBuilder) => {
          editBuilder.replace(fullRange, partialText);
        },
        {
          undoStopBefore: index === 0,
          undoStopAfter: index === chunks.length - 1,
        },
      );

      if (!applied) {
        throw new Error("VS Code 未能成功应用这次流式编辑。");
      }

      const percent = Math.min(95, Math.round(((index + 1) / chunks.length) * 95));
      onProgress?.({
        targetFile,
        percent,
        message: "正在流式写回文件",
      });

      await this.sleep(28);
    }
  }

  // 方法说明：
  // 根据目标文本长度生成若干渐进式写回分片。
  private buildStreamingChunks(content: string): string[] {
    if (!content) {
      return [""];
    }

    const chunkCount = Math.min(Math.max(Math.ceil(content.length / 900), 4), 12);
    const chunks: string[] = [];

    for (let index = 1; index <= chunkCount; index += 1) {
      const endIndex = Math.floor((content.length * index) / chunkCount);
      chunks.push(content.slice(0, endIndex));
    }

    if (chunks[chunks.length - 1] !== content) {
      chunks.push(content);
    }

    return chunks;
  }

  // 方法说明：
  // 统一上报动作应用的阶段性进度。
  private reportProgress(
    options: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    } | undefined,
    targetFile: string,
    percent: number,
    message: string,
  ): void {
    options?.onProgress?.({
      targetFile,
      percent,
      message,
    });
  }

  // 方法说明：
  // 为流式写回提供轻量停顿，使编辑过程可见。
  private async sleep(durationMs: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, durationMs));
  }

  // 方法说明：
  // 将文件系统路径规范化为适合比较的格式。
  private normalizeFilePath(filePath: string): string {
    const resolved = path.resolve(filePath);
    if (process.platform === "win32") {
      return resolved.replace(/\//g, "\\").toLowerCase();
    }

    return resolved;
  }

  // 方法说明：
  // 判断两个路径是否指向同一个文件。
  private isSameFilePath(leftPath: string, rightPath: string): boolean {
    return this.normalizeFilePath(leftPath) === this.normalizeFilePath(rightPath);
  }

  // 方法说明：
  // 判断目标路径是否位于指定工作区目录内。
  private isInsideWorkspace(targetPath: string, workspaceRoot: string): boolean {
    const normalizedTarget = this.normalizeFilePath(targetPath);
    const normalizedRoot = this.normalizeFilePath(workspaceRoot);
    const rootPrefix = normalizedRoot.endsWith(path.sep)
      ? normalizedRoot
      : normalizedRoot + path.sep;

    return normalizedTarget === normalizedRoot || normalizedTarget.startsWith(rootPrefix);
  }
}
