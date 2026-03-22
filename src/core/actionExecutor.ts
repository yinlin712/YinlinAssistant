import * as path from "path";
import * as vscode from "vscode";
import { AgentAction, AgentContext, AppliedAgentAction } from "./types";

// 这个执行器位于 VS Code 插件端。
// 它专门负责把 Python 后端返回的“待确认动作”真正落盘。
export class AgentActionExecutor {
  public async execute(actions: AgentAction[], context: AgentContext): Promise<AppliedAgentAction[]> {
    const results: AppliedAgentAction[] = [];

    for (const action of actions) {
      switch (action.kind) {
        case "create_file":
          results.push(await this.createFile(action, context));
          break;
        case "update_file":
          results.push(await this.updateExistingFile(action, context));
          break;
        case "update_documentation":
          results.push(await this.updateDocumentation(action, context));
          break;
      }
    }

    return results;
  }

  private async createFile(action: AgentAction, context: AgentContext): Promise<AppliedAgentAction> {
    try {
      const targetPath = this.ensureAllowedPath(action.targetFile, context);
      if (!targetPath) {
        return this.buildResult(action, "skipped", "目标路径不在当前工作区内，因此不会创建文件。");
      }

      const existingContent = await this.readCurrentText(targetPath);
      if (existingContent !== null) {
        return this.buildResult(action, "skipped", "目标文件已经存在，因此这次没有按 create_file 创建。");
      }

      await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(targetPath)));
      await this.writeTextToDisk(targetPath, action.updatedContent);
      return this.buildResult(action, "applied", action.summary || "已创建新文件。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  private async updateExistingFile(action: AgentAction, context: AgentContext): Promise<AppliedAgentAction> {
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

      await this.replaceWholeDocument(targetPath, nextText);
      return this.buildResult(action, "applied", action.summary || "已更新文件。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  private async updateDocumentation(action: AgentAction, context: AgentContext): Promise<AppliedAgentAction> {
    try {
      const targetPath = this.ensureAllowedPath(action.targetFile, context);
      if (!targetPath) {
        return this.buildResult(action, "skipped", "文档路径不在当前工作区内，因此不会写回。");
      }

      const currentText = await this.readCurrentText(targetPath);
      if (currentText === null) {
        await vscode.workspace.fs.createDirectory(vscode.Uri.file(path.dirname(targetPath)));
        await this.writeTextToDisk(targetPath, action.updatedContent);
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

      await this.replaceWholeDocument(targetPath, nextText);
      return this.buildResult(action, "applied", action.summary || "已更新文档。");
    } catch (error) {
      return this.buildResult(action, "failed", this.errorMessage(error));
    }
  }

  private ensureAllowedPath(targetFile: string, context: AgentContext): string | undefined {
    if (!targetFile.trim() || !context.workspaceRoot) {
      return undefined;
    }

    const workspaceRoot = path.resolve(context.workspaceRoot);
    const targetPath = path.resolve(targetFile);
    const relativePath = path.relative(workspaceRoot, targetPath);

    if (relativePath.startsWith("..") || path.isAbsolute(relativePath)) {
      return undefined;
    }

    return targetPath;
  }

  private async replaceWholeDocument(targetPath: string, nextText: string): Promise<void> {
    const document = await vscode.workspace.openTextDocument(vscode.Uri.file(targetPath));
    const currentText = document.getText();
    const normalizedText = this.normalizeText(nextText, currentText, document.eol);
    const fullRange = new vscode.Range(document.positionAt(0), document.positionAt(currentText.length));
    const edit = new vscode.WorkspaceEdit();

    edit.replace(document.uri, fullRange, normalizedText);

    const applied = await vscode.workspace.applyEdit(edit);
    if (!applied) {
      throw new Error("VS Code 未能成功应用这次编辑。");
    }

    await document.save();
  }

  private async readCurrentText(targetPath: string): Promise<string | null> {
    const openDocument = vscode.workspace.textDocuments.find((document) => document.fileName === targetPath);
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

  private async writeTextToDisk(targetPath: string, content: string): Promise<void> {
    const normalized = this.normalizeText(content, "", vscode.EndOfLine.CRLF);
    const bytes = Buffer.from(normalized, "utf8");
    await vscode.workspace.fs.writeFile(vscode.Uri.file(targetPath), bytes);
  }

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

  private matchesOriginalContent(currentText: string, originalContent: string): boolean {
    return this.canonicalize(currentText) === this.canonicalize(originalContent);
  }

  private canonicalize(content: string): string {
    return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  }

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

  private errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : String(error);
  }
}
