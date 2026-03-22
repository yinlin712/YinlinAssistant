// 文件说明：
// 本文件定义 React Webview 与插件端通信所需的消息和展示类型。

export type ChatRole = "user" | "agent" | "system";

// 类型说明：
// 表示对话区中的一条消息。
export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export type ActionKind = "create_file" | "update_file" | "update_documentation";

// 类型说明：
// 表示待确认方案中单个文件动作的预览信息。
export interface ProposalActionPreview {
  kind: ActionKind;
  targetFile: string;
  summary: string;
  diffText: string;
}

// 类型说明：
// 表示整个待确认方案的展示数据。
export interface PendingProposalPayload {
  title: string;
  summary: string;
  actions: ProposalActionPreview[];
}

// 类型说明：
// 表示首次加载 Webview 时所需的完整初始化数据。
export interface HydratePayload {
  messages: ChatMessage[];
  status: string;
  provider: string;
  activeFile?: string;
  noActiveFile: string;
  proposalTitle: string;
  proposalEmpty: string;
  pendingProposal: PendingProposalPayload | null;
}

// 类型说明：
// 表示状态栏刷新消息的载荷。
export interface StatusPayload {
  status: string;
  provider: string;
  activeFile?: string;
  noActiveFile: string;
}

// 类型说明：
// 约束插件端下发给 Webview 的消息格式。
export interface WebviewIncomingMessage {
  type: "hydrate" | "message" | "status" | "proposal" | "clearProposal";
  payload: unknown;
}
