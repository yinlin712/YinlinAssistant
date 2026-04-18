import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { AgentActionExecutor } from "./actionExecutor";
import { LocalModelProvider } from "./providers/localModelProvider";
import { MockModelProvider } from "./providers/mockProvider";
import {
  ActionExecutionProgress,
  AgentAction,
  AgentContext,
  AgentResponse,
  AgentStreamHandlers,
  ConversationTurn,
  ModelProvider,
} from "./types";

// 文件说明：
// 本文件定义插件端的 Agent 门面。
// 其职责是采集编辑器上下文、调用后端提供者，并在确认后执行文件动作。

const DOCUMENT_EXCERPT_LIMIT = 4000;
const FULL_DOCUMENT_LIMIT = 18000;
const PROJECT_ROOT_MARKERS = [
  ".git",
  "package.json",
  "requirements.txt",
  "environment.yml",
  "pyproject.toml",
];


// 类说明：
// 对外屏蔽上下文构建、提供者选择和动作执行细节。
export class CodingAgent {
  private readonly actionExecutor = new AgentActionExecutor();
  private lastContext?: AgentContext;

  // 方法说明：
  // 执行一次用户请求，并返回响应内容、提供者名称和上下文快照。
  public async run(
    prompt: string,
    conversationHistory: ConversationTurn[] = [],
  ): Promise<{ response: AgentResponse; provider: string; context: AgentContext }> {
    const context = this.buildContext();
    const provider = this.resolveProvider();
    const response = await provider.generate(prompt, context, conversationHistory);
    this.lastContext = context;

    return {
      response,
      provider: provider.name,
      context,
    };
  }

  // 方法说明：
  // 通过流式接口执行一次请求，用于当前文件改写时的实时 patch 预览。
  public async streamRun(
    prompt: string,
    conversationHistory: ConversationTurn[] = [],
    handlers: AgentStreamHandlers = {},
  ): Promise<{ response: AgentResponse; provider: string; context: AgentContext }> {
    const context = this.buildContext();
    const provider = this.resolveProvider();

    const response = provider.streamGenerate
      ? await provider.streamGenerate(prompt, context, conversationHistory, handlers)
      : await provider.generate(prompt, context, conversationHistory);

    this.lastContext = context;
    return {
      response,
      provider: provider.name,
      context,
    };
  }

  // 方法说明：
  // 在用户确认后执行待应用动作。
  public async applyProposedActions(
    actions: AgentAction[],
    preferredContext?: AgentContext,
    options?: {
      onProgress?: (progress: ActionExecutionProgress) => void;
    },
  ): Promise<AppliedActionsResult> {
    const context = this.buildExecutionContext(preferredContext);
    const appliedActions = await this.actionExecutor.execute(actions, context, options);

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
    const editor = vscode.window.activeTextEditor ?? vscode.window.visibleTextEditors[0];
    const activeFile = editor?.document.fileName;
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
      ?? this.resolveProjectRoot(activeFile);
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

  // 方法说明：
  // 合并当前编辑器上下文与上一次请求上下文，避免在 Webview 焦点下丢失活动文件信息。
  private buildExecutionContext(preferredContext?: AgentContext): AgentContext {
    const liveContext = this.buildContext();
    const fallbackContext = preferredContext ?? this.lastContext;

    const mergedContext: AgentContext = {
      workspaceRoot: liveContext.workspaceRoot ?? fallbackContext?.workspaceRoot,
      activeFile: liveContext.activeFile ?? fallbackContext?.activeFile,
      languageId: liveContext.languageId ?? fallbackContext?.languageId,
      selectedText: liveContext.selectedText ?? fallbackContext?.selectedText,
      documentText: liveContext.documentText ?? fallbackContext?.documentText,
      fullDocumentText: liveContext.fullDocumentText ?? fallbackContext?.fullDocumentText,
      systemPrompt: liveContext.systemPrompt || fallbackContext?.systemPrompt || "",
    };

    this.lastContext = mergedContext;
    return mergedContext;
  }

  // 方法说明：
  // 在未显式打开工作区时，尝试根据当前文件向上推断项目根目录。
  private resolveProjectRoot(activeFile?: string): string | undefined {
    if (!activeFile) {
      return undefined;
    }

    let currentDirectory = path.dirname(activeFile);
    const filesystemRoot = path.parse(currentDirectory).root;

    while (true) {
      if (PROJECT_ROOT_MARKERS.some((marker) => fs.existsSync(path.join(currentDirectory, marker)))) {
        return currentDirectory;
      }

      if (currentDirectory === filesystemRoot) {
        return undefined;
      }

      currentDirectory = path.dirname(currentDirectory);
    }
  }
}


// 类型说明：
// 保存插件端动作应用后的结果。
export interface AppliedActionsResult {
  context: AgentContext;
  appliedActions: ReturnType<AgentActionExecutor["execute"]> extends Promise<infer T> ? T : never;
}
