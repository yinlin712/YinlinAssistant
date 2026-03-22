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
