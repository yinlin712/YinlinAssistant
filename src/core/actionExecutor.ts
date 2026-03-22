import * as path from "path";
import * as vscode from "vscode";
import { AgentAction, AgentContext, AppliedAgentAction } from "./types";

// 文件说明：
// 本文件负责在插件端真正执行文件动作。
// 后端只负责规划，实际写入工作区文件必须由插件端完成。


// 类说明：
// 统一处理创建文件、更新代码文件和更新文档文件三类动作。
export class AgentActionExecutor {
  // 方法说明：
  // 顺序执行动作列表，并为每个动作返回执行结果。
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

  // 方法说明：
  // 执行“新建文件”动作。
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

  // 方法说明：
  // 执行“更新已有代码文件”动作。
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

  // 方法说明：
  // 执行“更新文档文件”动作。
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

  // 方法说明：
  // 校验目标路径是否位于当前工作区内。
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

  // 方法说明：
  // 将目标文件整篇替换为新内容。
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

  // 方法说明：
  // 优先从已打开文档中读取内容，否则回退到磁盘读取。
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
}
