// 文件说明：
// 本文件定义插件端通用类型。
// 这些类型会在面板、模型提供者、动作执行器等多个模块之间共享。

export type ChatRole = "user" | "agent" | "system";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

// 类型说明：
// 表示会发送给后端的最近对话上下文，仅保留用户与助手消息。
export interface ConversationTurn {
  role: "user" | "agent";
  content: string;
}

export interface AgentContext {
  workspaceRoot?: string;
  activeFile?: string;
  languageId?: string;
  selectedText?: string;
  documentText?: string;
  fullDocumentText?: string;
  systemPrompt: string;
}

export type AgentActionKind = "create_file" | "update_file" | "update_documentation";

export interface AgentAction {
  kind: AgentActionKind;
  targetFile: string;
  originalContent: string;
  updatedContent: string;
  summary?: string;
}

export interface AppliedAgentAction {
  kind: AgentActionKind;
  targetFile: string;
  status: "applied" | "skipped" | "failed";
  summary: string;
}

// 类型说明：
// 表示插件端在应用文件动作时产生的阶段性进度信息。
export interface ActionExecutionProgress {
  targetFile: string;
  percent: number;
  message: string;
}

export interface AgentResponse {
  content: string;
  mood: "idle" | "thinking" | "helpful";
  actions: AgentAction[];
  appliedActions: AppliedAgentAction[];
  requiresConfirmation: boolean;
  autoApplyActions: boolean;
  proposalSummary?: string;
}

// 类型说明：
// 约束模型流式返回阶段的回调结构。
export interface AgentStreamHandlers {
  onPatchPreview?: (updatedContent: string, context: AgentContext) => void;
  onMessageChunk?: (chunk: string) => void;
  onStatus?: (status: string) => void;
}

export interface ModelProvider {
  readonly name: string;
  generate(prompt: string, context: AgentContext, conversationHistory?: ConversationTurn[]): Promise<AgentResponse>;
  streamGenerate?(
    prompt: string,
    context: AgentContext,
    conversationHistory: ConversationTurn[],
    handlers: AgentStreamHandlers,
  ): Promise<AgentResponse>;
}

export interface ActionPreviewItem {
  kind: AgentActionKind;
  targetFile: string;
  summary: string;
  diffText: string;
}
