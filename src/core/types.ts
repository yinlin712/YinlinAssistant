// 文件说明：
// 本文件定义插件端通用类型。
// 这些类型会在面板、模型提供者、动作执行器等多个模块之间共享。

export type ChatRole = "user" | "agent" | "system";

export interface ChatMessage {
  role: ChatRole;
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

export interface AgentResponse {
  content: string;
  mood: "idle" | "thinking" | "helpful";
  actions: AgentAction[];
  appliedActions: AppliedAgentAction[];
  requiresConfirmation: boolean;
  proposalSummary?: string;
}

export interface ModelProvider {
  readonly name: string;
  generate(prompt: string, context: AgentContext): Promise<AgentResponse>;
}

export interface ActionPreviewItem {
  kind: AgentActionKind;
  targetFile: string;
  summary: string;
  diffText: string;
}
