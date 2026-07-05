export type ChatRole = "user" | "agent" | "system";
export type AvatarMode = "prototype" | "vrm" | "airi-ready";

/**
 * 表示聊天区中的一条消息。
 */
export interface ChatMessage {
  role: ChatRole;
  content: string;
}

/**
 * 表示流式输出中的增量片段。
 */
export interface MessageChunkPayload {
  role: Extract<ChatRole, "agent">;
  chunk: string;
}

export type ActionKind = "create_file" | "update_file" | "update_documentation";

/**
 * 表示待确认方案中的单个文件预览项。
 */
export interface ProposalActionPreview {
  kind: ActionKind;
  targetFile: string;
  summary: string;
  diffText: string;
}

/**
 * 表示待确认的修改方案。
 */
export interface PendingProposalPayload {
  title: string;
  summary: string;
  actions: ProposalActionPreview[];
  isStreaming: boolean;
}

/**
 * Webview 首次加载时的初始化数据。
 */
export interface HydratePayload {
  sessionId: string;
  messages: ChatMessage[];
  status: string;
  provider: string;
  activeFile?: string;
  noActiveFile: string;
  proposalTitle: string;
  proposalEmpty: string;
  pendingProposal: PendingProposalPayload | null;
}

/**
 * 顶部状态条刷新载荷。
 */
export interface StatusPayload {
  status: string;
  provider: string;
  activeFile?: string;
  noActiveFile: string;
}

/**
 * 数字人配置。
 */
export interface AvatarConfig {
  enabled: boolean;
  mode: AvatarMode;
  avatarUri?: string;
  vrmUri?: string;
  defaultPresetId?: string;
  presets: AvatarPresetConfig[];
}

export interface AvatarPresetConfig {
  id: string;
  label: string;
  avatarUri?: string;
  vrmUri?: string;
}

/**
 * 界面透明度偏好。
 */
export interface VisualPreferences {
  backgroundOpacity: number;
  chatOpacity: number;
}

/**
 * 语音交互配置，遵循 AIRI 兼容的转写接口思路。
 */
export interface VoiceInteractionConfig {
  enabled: boolean;
  baseUrl: string;
  apiKey?: string;
  model: string;
  language?: string;
  autoSubmit: boolean;
  autoSpeakReplies: boolean;
}

/**
 * 插件端返回的语音识别结果。
 */
export interface VoiceTranscriptPayload {
  text: string;
  autoSubmit: boolean;
  autoSpeakReplies: boolean;
}

/**
 * 插件端返回的实时语音转写片段。
 */
export interface VoiceInterimTranscriptPayload {
  sessionId: string;
  requestId: number;
  text: string;
}

/**
 * 语音处理状态载荷。
 */
export interface VoiceStatusPayload {
  phase: "listening" | "transcribing" | "ready" | "error";
  text: string;
  sessionId?: string;
}

/**
 * Webview 持久化缓存结构。
 */
export interface PersistedWebviewState {
  sessionId: string;
  messages: ChatMessage[];
  status: string;
  provider: string;
  activeFile: string;
  emptyProposalText: string;
  proposal: PendingProposalPayload | null;
  streamingAgentContent: string;
  visualPreferences: VisualPreferences;
}

/**
 * 插件端下发给 Webview 的消息类型。
 */
export interface WebviewIncomingMessage {
  type:
    | "hydrate"
    | "message"
    | "messageChunk"
    | "status"
    | "proposal"
    | "clearProposal"
    | "voiceStatus"
    | "voiceTranscript"
    | "voiceInterimTranscript"
    | "voiceError";
  payload: unknown;
}
