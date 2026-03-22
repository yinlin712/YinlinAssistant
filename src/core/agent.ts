import * as vscode from "vscode";
import { AgentActionExecutor } from "./actionExecutor";
import { LocalModelProvider } from "./providers/localModelProvider";
import { MockModelProvider } from "./providers/mockProvider";
import { AgentAction, AgentContext, AgentResponse, ModelProvider } from "./types";

const DOCUMENT_EXCERPT_LIMIT = 4000;
const FULL_DOCUMENT_LIMIT = 18000;

// 这个类位于 VS Code 插件端。
// 它负责收集上下文、把请求发给 Python 后端，并在用户确认后执行动作。
export class CodingAgent {
  private readonly actionExecutor = new AgentActionExecutor();

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

  public async applyProposedActions(actions: AgentAction[]): Promise<AppliedActionsResult> {
    const context = this.buildContext();
    const appliedActions = await this.actionExecutor.execute(actions, context);

    return {
      context,
      appliedActions,
    };
  }

  private resolveProvider(): ModelProvider {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const providerName = config.get<string>("modelProvider", "local");

    if (providerName === "mock") {
      return new MockModelProvider();
    }

    return new LocalModelProvider();
  }

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

export interface AppliedActionsResult {
  context: AgentContext;
  appliedActions: ReturnType<AgentActionExecutor["execute"]> extends Promise<infer T> ? T : never;
}
