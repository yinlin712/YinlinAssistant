import * as vscode from "vscode";
import { AgentActionExecutor } from "./actionExecutor";
import { LocalModelProvider } from "./providers/localModelProvider";
import { MockModelProvider } from "./providers/mockProvider";
import { AgentAction, AgentContext, AgentResponse, ModelProvider } from "./types";

// 文件说明：
// 本文件定义插件端的 Agent 门面。
// 其职责是采集编辑器上下文、调用后端提供者，并在确认后执行文件动作。

const DOCUMENT_EXCERPT_LIMIT = 4000;
const FULL_DOCUMENT_LIMIT = 18000;


// 类说明：
// 对外屏蔽上下文构建、提供者选择和动作执行细节。
export class CodingAgent {
  private readonly actionExecutor = new AgentActionExecutor();

  // 方法说明：
  // 执行一次用户请求，并返回响应内容、提供者名称和上下文快照。
  public async run(prompt: string): Promise<{ response: AgentResponse; provider: string; context: AgentContext }> {
    const context = this.buildContext();
    const provider = this.resolveProvider();
    const response = await provider.generate(prompt, context);

    return {
      response,
      provider: provider.name,
      context,
    };
  }

  // 方法说明：
  // 在用户确认后执行待应用动作。
  public async applyProposedActions(actions: AgentAction[]): Promise<AppliedActionsResult> {
    const context = this.buildContext();
    const appliedActions = await this.actionExecutor.execute(actions, context);

    return {
      context,
      appliedActions,
    };
  }

  // 方法说明：
  // 根据插件配置选择当前使用的模型提供者。
  private resolveProvider(): ModelProvider {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const providerName = config.get<string>("modelProvider", "local");

    if (providerName === "mock") {
      return new MockModelProvider();
    }

    return new LocalModelProvider();
  }

  // 方法说明：
  // 从当前活动编辑器和插件配置中构造一次请求需要的上下文。
  private buildContext(): AgentContext {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const editor = vscode.window.activeTextEditor;
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const activeFile = editor?.document.fileName;
    const languageId = editor?.document.languageId;
    const selectedText = editor?.document.getText(editor.selection);
    const fullDocument = editor?.document.getText() ?? "";
    const documentText = fullDocument.slice(0, DOCUMENT_EXCERPT_LIMIT);
    const fullDocumentText = fullDocument.length > 0 && fullDocument.length <= FULL_DOCUMENT_LIMIT
      ? fullDocument
      : undefined;

    return {
      workspaceRoot,
      activeFile,
      languageId,
      selectedText: selectedText || undefined,
      documentText: documentText || undefined,
      fullDocumentText,
      systemPrompt: config.get<string>(
        "systemPrompt",
        "You are a calm and capable coding assistant embedded in VS Code. Help with code understanding, generation, debugging, and refactoring."
      ),
    };
  }
}


// 类型说明：
// 保存插件端动作应用后的结果。
export interface AppliedActionsResult {
  context: AgentContext;
  appliedActions: ReturnType<AgentActionExecutor["execute"]> extends Promise<infer T> ? T : never;
}
