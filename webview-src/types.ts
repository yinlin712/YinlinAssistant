export type ChatRole = "user" | "agent" | "system";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export type ActionKind = "create_file" | "update_file" | "update_documentation";

export interface ProposalActionPreview {
  kind: ActionKind;
  targetFile: string;
  summary: string;
  diffText: string;
}

export interface PendingProposalPayload {
  title: string;
  summary: string;
  actions: ProposalActionPreview[];
}

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

export interface StatusPayload {
  status: string;
  provider: string;
  activeFile?: string;
  noActiveFile: string;
}

export interface WebviewIncomingMessage {
  type: "hydrate" | "message" | "status" | "proposal" | "clearProposal";
  payload: unknown;
}
